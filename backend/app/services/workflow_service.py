"""向导式工作流引擎 — 流程模板、步骤推进、自动检测、旧项目推断。"""
import copy
import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import BusinessError
from app.models.billing import Billing, Invoice
from app.models.capital import CapitalTransaction
from app.models.delivery import DeliveryStage, Order
from app.models.device import Device, DeviceStage
from app.models.leasing import LeasingProcess
from app.models.project import Contract, Project
from app.models.project_workflow import ProjectWorkflow
from app.models.sales_order import SalesOrder
from app.models.step_audit_log import StepAuditLog
from app.models.user import User
from app.models.acceptance import AcceptanceRecord
from app.models.profit_scenario import ProfitScenario
from app.models.service_confirmation import ServiceConfirmation
from app.models.workflow_template import WorkflowTemplate

logger = logging.getLogger(__name__)

# 表名 → ORM 类（completion_check 白名单 + 实体映射，单一来源）
_TABLE_CLASSES: dict[str, type] = {
    "projects": Project,
    "contracts": Contract,
    "sales_orders": SalesOrder,
    "orders": Order,
    "capital_transactions": CapitalTransaction,
    "leasing_processes": LeasingProcess,
    "acceptance_records": AcceptanceRecord,
    "delivery_stages": DeliveryStage,
    "billings": Billing,
    "service_confirmations": ServiceConfirmation,
    "invoices": Invoice,
    "profit_scenarios": ProfitScenario,
    "devices": Device,            # 一期 W3-4：设备粒度模板 completion_check
    "device_stages": DeviceStage,
}
ALLOWED_TABLES = frozenset(_TABLE_CLASSES)  # 由 _TABLE_CLASSES 自动派生

# 间接 FK 映射：表 → (FK列, 中间表类)  — 用于表上无 project_id 时通过中间表过滤
_FK_TO_PROJECT: dict[str, tuple] = {
    "invoices": ("contract_id", Contract),
    "service_confirmations": ("sales_order_id", SalesOrder),
    "delivery_stages": ("order_id", Order),
    "device_stages": ("device_id", Device),  # 一期 W3-4：经 device_id→devices→project_id 过滤
}


# —— 创建与查询 ——

def create_workflow(db: Session, *, project_id: uuid.UUID, template_id: uuid.UUID | None = None) -> ProjectWorkflow:
    """从模板深拷贝 steps，自动标记 Step 1 完成。"""
    proj = db.get(Project, project_id)
    if not proj:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)

    if template_id:
        tmpl = db.get(WorkflowTemplate, template_id)
        if not tmpl:
            raise BusinessError("NOT_FOUND", "模板不存在", 404)
        steps = copy.deepcopy(tmpl.steps)
    else:
        steps = _default_steps()

    # Step 1 自动完成
    step1_done = bool(steps and steps[0].get("seq") == 1)
    if step1_done:
        steps[0]["status"] = "done"
        steps[0]["completed_at"] = datetime.utcnow().isoformat()

    first_pending = _find_next_required(steps, 1 if step1_done else 0)
    wf = ProjectWorkflow(
        project_id=project_id, template_id=template_id,
        steps=steps, current_step=first_pending, status="进行中",
    )
    db.add(wf)
    db.flush()

    # 记录 Step 1
    db.add(StepAuditLog(
        project_workflow_id=wf.id, step_seq=1,
        step_name=steps[0].get("name", "项目建立"),
        action="complete", operator_id=None, operated_at=datetime.utcnow(),
    ))
    db.flush()
    return wf


def get_workflow(db: Session, project_id: uuid.UUID) -> ProjectWorkflow | None:
    """获取项目流程，不存在则尝试推断生成。"""
    wf = db.execute(
        select(ProjectWorkflow).where(ProjectWorkflow.project_id == project_id)
    ).scalar_one_or_none()
    if not wf:
        wf = infer_workflow(db, project_id)
    if wf:
        _attach_step_entity_refs(db, wf)
    return wf


def get_workflow_for_update(db: Session, project_id: uuid.UUID) -> ProjectWorkflow | None:
    """SELECT FOR UPDATE 锁行，防并发双推进。"""
    return db.execute(
        select(ProjectWorkflow)
        .where(ProjectWorkflow.project_id == project_id)
        .with_for_update()
    ).scalar_one_or_none()


def get_my_tasks(db: Session, user_id: uuid.UUID) -> list[dict]:
    """首页待办：返回 current_step 匹配当前用户角色的 pending 步骤。"""
    user = db.get(User, user_id)
    if not user:
        return []

    wfs = db.execute(
        select(ProjectWorkflow).where(
            ProjectWorkflow.status == "进行中",
            ProjectWorkflow.deleted_at.is_(None),
        )
    ).scalars().all()

    # 批量取项目，避免 N+1（此函数被 Dashboard 每 30s 轮询）
    project_ids = [wf.project_id for wf in wfs]
    project_map: dict[uuid.UUID, Project] = {}
    if project_ids:
        projects = db.execute(
            select(Project).where(Project.id.in_(project_ids))
        ).scalars().all()
        project_map = {p.id: p for p in projects}

    tasks = []
    for wf in wfs:
        proj = project_map.get(wf.project_id)
        if not proj:
            continue
        current = _step_by_seq(wf.steps, wf.current_step)
        if current and current.get("doer_role") == user.role and current.get("status") == "pending":
            tasks.append({
                "project_id": str(wf.project_id),
                "project_name": proj.name,
                "step_seq": current["seq"],
                "step_name": current["name"],
                "doer_role": current.get("doer_role", ""),
                "drawer": current.get("drawer", False),
                "drawer_schema": current.get("drawer_schema"),
                "module": current.get("module", ""),
            })
    return tasks


# —— 推进 ——

def after_action(db: Session, project_id: uuid.UUID):
    """业务操作成功后调用（同步，同一事务内）。SELECT FOR UPDATE 锁行。
    循环推进：当前步骤完成后继续检测后续 required 步骤，直到某步 check 不通过。
    内部 try/except：推进失败记日志，不向调用方抛。"""
    try:
        wf = get_workflow_for_update(db, project_id)
        if not wf or wf.status != "进行中":
            return
        while True:
            current = _step_by_seq(wf.steps, wf.current_step)
            if not current or current.get("status") != "pending":
                return
            if not check_completion(db, project_id, current):
                return
            _mark_done(db, wf, current)
            if wf.status != "进行中":
                return
    except Exception:
        logger.exception("after_action failed for project %s", project_id)


def check_completion(db: Session, project_id: uuid.UUID, step: dict) -> bool:
    """根据 completion_check 查询检测步骤是否完成。"""
    check = step.get("completion_check")
    if not check:
        return False
    table_name = check["table"]
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"table {table_name} not in whitelist")

    conditions = check.get("conditions", {})
    min_count = check.get("min_count", 1)
    table_cls = _table_class(table_name)
    if not table_cls:
        return False

    resolved = {k: project_id if v == "{{project_id}}" else v for k, v in conditions.items()}
    where_clauses: list = []
    for col, val in resolved.items():
        if hasattr(table_cls, col):
            col_attr = getattr(table_cls, col)
            if val is None:
                where_clauses.append(col_attr.is_(None))
            else:
                where_clauses.append(col_attr == val)
        elif col == "project_id" and table_name in _FK_TO_PROJECT:
            # 间接 FK：通过中间表过滤
            fk_col, parent_cls = _FK_TO_PROJECT[table_name]
            subq = (
                select(parent_cls.id)
                .where(parent_cls.project_id == project_id)
                .where(parent_cls.deleted_at.is_(None))
            )
            where_clauses.append(getattr(table_cls, fk_col).in_(subq))
        else:
            continue

    if not where_clauses:
        return False

    count = db.execute(
        select(func.count()).select_from(table_cls).where(*where_clauses)
    ).scalar() or 0
    return count >= min_count


def refresh_all_steps(db: Session, project_id: uuid.UUID) -> ProjectWorkflow:
    """全量重检：逐步骤检测完成状态，支持红冲回退。skip 为终态不参与回退。"""
    wf = get_workflow(db, project_id)
    if not wf:
        raise BusinessError("NOT_FOUND", "项目流程不存在", 404)

    changed = False
    first_pending = None
    for step in wf.steps:
        if step.get("status") == "skip":
            if first_pending is None and step.get("required", True):
                first_pending = step["seq"]
            continue
        if check_completion(db, project_id, step):
            if step.get("status") != "done":
                step["status"] = "done"
                step["completed_at"] = datetime.utcnow().isoformat()
                changed = True
        else:
            if step.get("status") == "done":
                step["status"] = "pending"  # 回退
                step["completed_at"] = None
                changed = True
            if first_pending is None and step.get("required", True):
                first_pending = step["seq"]

    if first_pending is not None:
        wf.current_step = first_pending
    else:
        wf.current_step = len(wf.steps)
        wf.status = "已完成"

    if changed:
        # steps 是 JSONB 列，原地改 dict 不会触发脏检查，必须显式标记
        flag_modified(wf, "steps")
        db.flush()
    return wf


# —— 手动控制 ——

def skip_step(db: Session, project_id: uuid.UUID, seq: int, reason: str, operator_id: uuid.UUID):
    """跳过步骤。required=false 的步骤 doer 可跳过；required=true 需 FINANCE_DIRECTOR+。"""
    user = db.get(User, operator_id)
    if not user:
        raise BusinessError("NOT_FOUND", "用户不存在", 404)

    wf = get_workflow(db, project_id)
    if not wf:
        raise BusinessError("NOT_FOUND", "项目流程不存在", 404)

    step = _step_by_seq(wf.steps, seq)
    if not step:
        raise BusinessError("NOT_FOUND", f"步骤 seq={seq} 不存在", 404)

    if step.get("required", True) and user.role not in ("FINANCE_DIRECTOR", "ADMIN"):
        raise BusinessError("FORBIDDEN", "强制跳过必做步骤需要 FINANCE_DIRECTOR 或 ADMIN 权限", 403)

    step["status"] = "skip"
    step["completed_at"] = datetime.utcnow().isoformat()
    step["completed_by"] = str(operator_id)
    _advance_current(wf)
    flag_modified(wf, "steps")  # JSONB 原地修改需显式标记脏

    db.add(StepAuditLog(
        project_workflow_id=wf.id, step_seq=seq,
        step_name=step.get("name", ""), action="skip",
        operator_id=operator_id, operated_at=datetime.utcnow(), note=reason,
    ))
    db.flush()


def mark_step_done(db: Session, project_id: uuid.UUID, seq: int, note: str | None, operator_id: uuid.UUID):
    """手动标记完成（兜底通道）。需 FINANCE_DIRECTOR+。"""
    user = db.get(User, operator_id)
    if not user:
        raise BusinessError("NOT_FOUND", "用户不存在", 404)
    if user.role not in ("FINANCE_DIRECTOR", "ADMIN"):
        raise BusinessError("FORBIDDEN", "需要 FINANCE_DIRECTOR 或 ADMIN 权限", 403)

    wf = get_workflow(db, project_id)
    if not wf:
        raise BusinessError("NOT_FOUND", "项目流程不存在", 404)

    step = _step_by_seq(wf.steps, seq)
    if not step:
        raise BusinessError("NOT_FOUND", f"步骤 seq={seq} 不存在", 404)

    step["status"] = "done"
    step["completed_at"] = datetime.utcnow().isoformat()
    step["completed_by"] = str(operator_id)
    _advance_current(wf)
    flag_modified(wf, "steps")  # JSONB 原地修改需显式标记脏

    db.add(StepAuditLog(
        project_workflow_id=wf.id, step_seq=seq,
        step_name=step.get("name", ""), action="manual_complete",
        operator_id=operator_id, operated_at=datetime.utcnow(), note=note,
    ))
    db.flush()


def portfolio(db: Session) -> list[dict]:
    """项目组合总览：每项目 current_step/状态/角色/停滞天数。"""
    wfs = db.execute(
        select(ProjectWorkflow).where(ProjectWorkflow.deleted_at.is_(None))
    ).scalars().all()

    project_ids = [wf.project_id for wf in wfs]
    project_map: dict[uuid.UUID, Project] = {}
    if project_ids:
        projects = db.execute(
            select(Project).where(Project.id.in_(project_ids))
        ).scalars().all()
        project_map = {p.id: p for p in projects}

    rows = []
    for wf in wfs:
        proj = project_map.get(wf.project_id)
        if not proj:
            continue
        current = _step_by_seq(wf.steps, wf.current_step)
        stagnation = (datetime.utcnow() - wf.updated_at.replace(tzinfo=None)).days if wf.updated_at else 0
        rows.append({
            "project_id": str(wf.project_id), "project_name": proj.name,
            "current_step": wf.current_step, "current_step_name": current.get("name", "") if current else "",
            "doer_role": current.get("doer_role", "") if current else "",
            "status": wf.status, "stagnation_days": stagnation,
            "total_steps": len(wf.steps), "done_count": sum(1 for s in wf.steps if s.get("status") == "done"),
        })
    return rows


def update_step_config(db: Session, project_id: uuid.UUID, seq: int, **kwargs):
    """调整步骤配置。仅 ADMIN。"""
    wf = get_workflow(db, project_id)
    if not wf:
        raise BusinessError("NOT_FOUND", "项目流程不存在", 404)
    step = _step_by_seq(wf.steps, seq)
    if not step:
        raise BusinessError("NOT_FOUND", f"步骤 seq={seq} 不存在", 404)
    for k, v in kwargs.items():
        if v is not None:
            step[k] = v
    flag_modified(wf, "steps")  # JSONB 原地修改需显式标记脏
    db.flush()


# —— 旧项目兼容 ——

def infer_workflow(db: Session, project_id: uuid.UUID) -> ProjectWorkflow | None:
    """从 24 张业务表反推进度。幂等：已有记录直接返回。"""
    existing = db.execute(
        select(ProjectWorkflow).where(ProjectWorkflow.project_id == project_id)
    ).scalar_one_or_none()
    if existing:
        return existing

    proj = db.get(Project, project_id)
    if not proj:
        return None

    steps = _default_steps()
    first_pending = None
    for step in steps:
        if check_completion(db, project_id, step):
            step["status"] = "done"
            step["completed_at"] = datetime.utcnow().isoformat()
        else:
            if first_pending is None and step.get("required", True):
                first_pending = step["seq"]

    if first_pending is None:
        first_pending = len(steps)

    wf = ProjectWorkflow(
        project_id=project_id, steps=steps,
        current_step=first_pending,
        status="已完成" if first_pending == len(steps) else "进行中",
    )
    db.add(wf)
    db.flush()

    db.add(StepAuditLog(
        project_workflow_id=wf.id, step_seq=0, step_name="infer",
        action="infer", operator_id=None, operated_at=datetime.utcnow(),
        note=f"从存量数据推断，current_step={first_pending}",
    ))
    db.flush()
    return wf


# —— 内部辅助 ——

def _attach_step_entity_refs(db: Session, wf: ProjectWorkflow) -> None:
    """为可跳转步骤补对应实体 id + 数量（步骤导航深链数据源）。

    按步骤 name 匹配而非 seq：模板会重编号（seed.py 15 步模板重排 seq），
    但 name 在三个模板中稳定（销售合同/采购合同/批次订单）。
    订单步在标准模板中名为「采购订单」（roleGuide.ts aliases 亦列出），一并覆盖。
    只在读取路径原地补字段，不 flag_modified——引用是计算产物，不落库。
    """
    pid = wf.project_id

    def entities(model, **where):
        q = select(model).where(model.project_id == pid, model.deleted_at.is_(None))
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return db.execute(q.order_by(model.created_at.asc())).scalars().all()

    sales = entities(Contract, type="SALES")
    purchases = entities(Contract, type="PURCHASE")
    orders = entities(Order)
    for s in wf.steps:
        name = s.get("name")
        if name == "销售合同" and sales:
            s["sales_contract_id"] = str(sales[0].id)
            s["sales_contract_count"] = len(sales)
        elif name == "采购合同" and purchases:
            s["purchase_contract_id"] = str(purchases[0].id)
            s["purchase_contract_count"] = len(purchases)
        elif name in ("批次订单", "采购订单") and orders:
            s["order_id"] = str(orders[0].id)
            s["order_count"] = len(orders)


def _step_by_seq(steps: list[dict], seq: int) -> dict | None:
    return next((s for s in steps if s.get("seq") == seq), None)


def _find_next_required(steps: list[dict], from_seq: int) -> int:
    """找到 from_seq 之后第一个 required=true 的步骤的 seq。"""
    candidates = sorted(
        [s for s in steps if s.get("seq", 0) > from_seq and s.get("required", True)],
        key=lambda s: s["seq"],
    )
    return candidates[0]["seq"] if candidates else len(steps)


def _mark_done(db: Session, wf: ProjectWorkflow, step: dict, operator_id: uuid.UUID | None = None):
    step["status"] = "done"
    step["completed_at"] = datetime.utcnow().isoformat()
    step["completed_by"] = str(operator_id) if operator_id else None
    _advance_current(wf)
    flag_modified(wf, "steps")  # JSONB 原地修改需显式标记脏
    db.add(StepAuditLog(
        project_workflow_id=wf.id, step_seq=step["seq"],
        step_name=step.get("name", ""), action="complete",
        operator_id=operator_id, operated_at=datetime.utcnow(),
    ))
    db.flush()


def _advance_current(wf: ProjectWorkflow):
    wf.current_step = _find_next_required(wf.steps, wf.current_step)
    if wf.current_step >= len(wf.steps):
        # 检查是否所有 required 都 done/skip
        all_done = all(
            s.get("status") in ("done", "skip") or not s.get("required", True)
            for s in wf.steps
        )
        if all_done:
            wf.status = "已完成"


def _table_class(table_name: str):
    return _TABLE_CLASSES.get(table_name)


def _check(table: str, min_count: int = 1, **conditions) -> dict:
    """completion_check 快捷构造：查某表满足条件行数 >= min_count。"""
    return {"table": table, "conditions": conditions, "min_count": min_count}


def _step(seq: int, name: str, module: str, action: str, *,
          doer_role: str, check: dict | None = None,
          required: bool = True, drawer: bool = False,
          drawer_schema: str | None = None, approver_role: str | None = None,
          prefill: dict | None = None, context_output: list | None = None,
          action_chain: list | None = None) -> dict:
    return {
        "seq": seq, "name": name, "module": module, "action": action,
        "required": required, "drawer": drawer, "drawer_schema": drawer_schema,
        "doer_role": doer_role, "approver_role": approver_role,
        "prefill": prefill or {}, "context_output": context_output or [],
        "action_chain": action_chain or [],
        "completion_check": check or {},
        "status": "pending", "completed_at": None, "completed_by": None,
    }


def _default_steps() -> list[dict]:
    """标准金租 18 步模板（兜底用，实际应通过 workflow_templates 获取）。"""
    pid = {"project_id": "{{project_id}}"}
    return [
        _step(1, "项目建立", "project", "create_project", doer_role="PROCUREMENT",
              check=_check("projects", id="{{project_id}}", deleted_at=None)),
        _step(2, "销售合同", "contract", "create_contract", doer_role="PROCUREMENT",
              prefill=pid, context_output=["contract_id"],
              check=_check("contracts", project_id="{{project_id}}", type="SALES", deleted_at=None)),
        _step(3, "采购合同", "contract", "create_contract", doer_role="PROCUREMENT",
              prefill=pid, context_output=["contract_id"],
              check=_check("contracts", project_id="{{project_id}}", type="PURCHASE", deleted_at=None)),
        _step(4, "销售订单", "sales_order", "create_sales_order", doer_role="PROCUREMENT",
              prefill=pid, context_output=["sales_order_id"],
              check=_check("sales_orders", project_id="{{project_id}}", deleted_at=None)),
        _step(5, "采购订单", "order", "create_order", doer_role="PROCUREMENT",
              prefill=pid, context_output=["order_id"],
              check=_check("orders", project_id="{{project_id}}", deleted_at=None)),
        _step(6, "银行流贷入金", "capital", "record_transaction", doer_role="FINANCE_STAFF",
              drawer=True, drawer_schema="capital_in",
              prefill={**pid, "source_type": "银行流贷", "direction": "IN"},
              context_output=["capital_transaction_id"],
              check=_check("capital_transactions", project_id="{{project_id}}", source_type="银行流贷", direction="IN", deleted_at=None)),
        _step(7, "自有资金入金", "capital", "record_transaction", doer_role="FINANCE_STAFF",
              drawer=True, drawer_schema="capital_in",
              prefill={**pid, "source_type": "自有资金", "direction": "IN"},
              context_output=["capital_transaction_id"],
              check=_check("capital_transactions", project_id="{{project_id}}", source_type="自有资金", direction="IN", deleted_at=None)),
        _step(8, "预付采购款", "capital", "record_transaction", doer_role="FINANCE_STAFF",
              drawer=True, drawer_schema="capital_out",
              prefill={**pid, "direction": "OUT"}, context_output=["capital_transaction_id"],
              check=_check("capital_transactions", project_id="{{project_id}}", direction="OUT", deleted_at=None)),
        _step(9, "金租申请", "leasing", "create_process", doer_role="DELIVERY",
              prefill=pid, context_output=["leasing_process_id"],
              check=_check("leasing_processes", project_id="{{project_id}}", deleted_at=None)),
        _step(10, "金租放款+置换", "leasing", "disburse", doer_role="FINANCE_DIRECTOR",
              approver_role="FINANCE_DIRECTOR",
              check=_check("leasing_processes", project_id="{{project_id}}", status="已放款", deleted_at=None)),
        _step(11, "采购验收", "acceptance", "create+approve", doer_role="PROCUREMENT",
              drawer=True, drawer_schema="acceptance", approver_role="FINANCE_DIRECTOR",
              prefill={**pid, "acceptance_type": "采购验收"}, context_output=["acceptance_id"],
              action_chain=["create", "upload", "approve"],
              check=_check("acceptance_records", project_id="{{project_id}}", acceptance_type="采购验收", status="已通过", deleted_at=None)),
        _step(12, "交付6阶段", "delivery", "advance_stage", doer_role="PROCUREMENT",
              check=_check("delivery_stages", min_count=6, project_id="{{project_id}}", status="已完成", deleted_at=None)),
        _step(13, "销售验收", "acceptance", "create+approve", doer_role="DELIVERY",
              drawer=True, drawer_schema="acceptance", approver_role="FINANCE_DIRECTOR",
              prefill={**pid, "acceptance_type": "销售验收"}, context_output=["acceptance_id"],
              action_chain=["create", "upload", "approve"],
              check=_check("acceptance_records", project_id="{{project_id}}", acceptance_type="销售验收", status="已通过", deleted_at=None)),
        _step(14, "点亮", "order", "light_on", doer_role="PROCUREMENT",
              check=_check("orders", project_id="{{project_id}}", status="已点亮", deleted_at=None)),
        _step(15, "计费", "billing", "generate_billing", doer_role="FINANCE_STAFF",
              drawer=True, drawer_schema="billing_confirm",
              prefill=pid, context_output=["billing_id"],
              check=_check("billings", project_id="{{project_id}}", deleted_at=None)),
        _step(16, "客户确认", "confirmation", "confirm", doer_role="FINANCE_STAFF",
              drawer=True, drawer_schema="confirmation",
              prefill=pid, context_output=["confirmation_id"],
              check=_check("service_confirmations", project_id="{{project_id}}", status="已确认", deleted_at=None)),
        _step(17, "开票+回款+核销", "invoice", "create+pay+reconcile", doer_role="FINANCE_STAFF",
              drawer=True, drawer_schema="invoice_issue", approver_role="FINANCE_DIRECTOR",
              prefill=pid, context_output=["invoice_id"],
              action_chain=["create", "pay", "reconcile"],
              check=_check("invoices", project_id="{{project_id}}", status="已核销", deleted_at=None)),
        _step(18, "盈利测算", "profit", "calculate", doer_role="FINANCE_STAFF",
              required=False, prefill=pid,
              check=_check("profit_scenarios", project_id="{{project_id}}", is_actual=True, deleted_at=None)),
    ]


def _device_flow_steps() -> list[dict]:
    """设备粒度 7 节点向导模板（一期 W3-4）：completion_check 指向 devices/device_stages。

    模板选择沿用 template_id（create_project 时操作员手选）——规格 L259 的「随 flow_type 自动匹配」本轮不实现。
    节点推进/点亮步骤 min_count=1 作为 W3-4 壳（至少一台设备达到该节点）；按台计费在 W5-6。
    device_stages 经 _FK_TO_PROJECT 间接关联 project_id，防跨项目误判（审计 A2 / D6）。
    """
    pid = {"project_id": "{{project_id}}"}
    return [
        _step(1, "项目建立", "project", "create_project", doer_role="PROCUREMENT",
              check=_check("projects", id="{{project_id}}", deleted_at=None)),
        _step(2, "销售合同", "contract", "create_contract", doer_role="PROCUREMENT",
              prefill=pid, context_output=["contract_id"],
              check=_check("contracts", project_id="{{project_id}}", type="SALES", deleted_at=None)),
        _step(3, "采购合同", "contract", "create_contract", doer_role="PROCUREMENT",
              prefill=pid,
              check=_check("contracts", project_id="{{project_id}}", type="PURCHASE", deleted_at=None)),
        _step(4, "批次订单", "order", "create_order", doer_role="PROCUREMENT",
              prefill={**pid, "is_batch": True},
              check=_check("orders", project_id="{{project_id}}", is_batch=True, deleted_at=None)),
        _step(5, "设备导入", "device", "import_devices", doer_role="DELIVERY",
              prefill=pid,
              check=_check("devices", project_id="{{project_id}}", deleted_at=None, min_count=1)),
        _step(6, "设备到货", "device", "advance_device_stage", doer_role="DELIVERY",
              check=_check("device_stages", project_id="{{project_id}}", stage="到货", status="已完成", min_count=1)),
        _step(7, "设备上架", "device", "advance_device_stage", doer_role="DELIVERY",
              check=_check("device_stages", project_id="{{project_id}}", stage="上架", status="已完成", min_count=1)),
        _step(8, "点亮验收", "device", "advance_device_stage", doer_role="DELIVERY",
              check=_check("device_stages", project_id="{{project_id}}", stage="点亮验收", status="已完成", min_count=1)),
        _step(9, "金租放款", "leasing", "disburse", doer_role="FINANCE_STAFF",
              required=False, prefill=pid,  # M2：可选——自有设备无金租；点亮达阈值已自动建申请，此步走放款
              check=_check("leasing_processes", project_id="{{project_id}}", status="已放款", deleted_at=None)),
        _step(10, "按台计费", "billing", "generate_billing", doer_role="FINANCE_STAFF",
              required=False, prefill=pid,
              check=_check("billings", project_id="{{project_id}}", deleted_at=None)),
        _step(11, "盈利测算", "profit", "calculate", doer_role="FINANCE_STAFF",
              required=False, prefill=pid,
              check=_check("profit_scenarios", project_id="{{project_id}}", is_actual=True, deleted_at=None)),
    ]
