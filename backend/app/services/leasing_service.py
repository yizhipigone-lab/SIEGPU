"""金租流程服务（一期核心）。对应设计书 §4.4/§5.5。

- 建申请自动生成 9 标准节点；
- 节点按状态机推进；
- 放款：同事务写 capital_transaction(放款入金) + 生成 N 期还款计划，靠 plan_generated + 行锁幂等。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.capital import CapitalTransaction
from app.models.leasing import LeasingNode, LeasingProcess
from app.models.master import Supplier
from app.models.project import Project
from app.models.repayment import Repayment
from app.utils.repayment_plan import generate_plan

# 9 个标准节点（按序）
STANDARD_NODES = ["接触", "业务交流", "资料提交", "金租审核", "一次上会", "二次上会", "访谈", "批方案", "放款"]

# 节点状态机（合法迁移）
NODE_TRANSITIONS = {
    "未开始": {"进行中"},
    "进行中": {"已完成", "卡住"},
    "卡住": {"进行中"},
    "已完成": set(),
}


def create_process(db: Session, *, project_id, supplier_id, total_amount, annual_rate=None,
                   term_periods=None, payment_freq=None, repayment_method=None,
                   start_date=None, notes=None) -> LeasingProcess:
    proj = db.get(Project, project_id)
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "供应商不存在", 404)
    if sup.type != "资金供应商":
        raise BusinessError("BAD_REQUEST", "供应商不是金租公司（type 必须为 资金供应商）", 400)

    proc = LeasingProcess(
        project_id=project_id, supplier_id=supplier_id, total_amount=total_amount,
        annual_rate=annual_rate, term_periods=term_periods, payment_freq=payment_freq,
        repayment_method=repayment_method, start_date=start_date, status="进行中", notes=notes,
    )
    db.add(proc)
    db.flush()
    for i, name in enumerate(STANDARD_NODES, 1):
        db.add(LeasingNode(process_id=proc.id, node_name=name, seq=i, status="未开始"))
    db.flush()
    from app.services import workflow_service as _wf
    _wf.after_action(db, project_id)
    return proc


def list_processes(db: Session, project_id=None):
    stmt = select(LeasingProcess).order_by(LeasingProcess.created_at.desc())
    if project_id:
        stmt = stmt.where(LeasingProcess.project_id == project_id)
    return db.execute(stmt).scalars().all()


def get_process(db: Session, process_id):
    proc = db.get(LeasingProcess, process_id)
    if not proc or proc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "金租申请不存在", 404)
    nodes = db.execute(
        select(LeasingNode).where(LeasingNode.process_id == process_id).order_by(LeasingNode.seq)
    ).scalars().all()
    return proc, nodes


def advance_node(db: Session, *, node_id, status, actual_date=None, stuck_reason=None) -> LeasingNode:
    node = db.get(LeasingNode, node_id)
    if not node or node.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "节点不存在", 404)
    allowed = NODE_TRANSITIONS.get(node.status, set())
    if status not in allowed:
        raise BusinessError("ILLEGAL_TRANSITION", f"节点不允许 {node.status} → {status}", 409)
    node.status = status
    if status == "已完成" and actual_date:
        node.actual_date = actual_date
    if status == "卡住" and stuck_reason:
        node.stuck_reason = stuck_reason
    db.flush()
    return node


def disburse(db: Session, *, process_id, actual_disbursement_amount: Decimal,
             disbursement_date: date, disbursed_by, note: str | None = None):
    """放款：同事务生成放款入金流水 + N 期还款计划。幂等：plan_generated + SELECT FOR UPDATE。"""
    proc = db.execute(
        select(LeasingProcess).where(LeasingProcess.id == process_id).with_for_update()
    ).scalar_one_or_none()
    if not proc:
        raise BusinessError("NOT_FOUND", "金租申请不存在", 404)
    if proc.plan_generated or proc.status == "已放款":
        raise BusinessError("DUPLICATE", "已放款/已生成还款计划", 409)
    if proc.status not in ("进行中", "已批"):
        raise BusinessError("ILLEGAL_TRANSITION", f"不允许 {proc.status} → 已放款", 409)
    if not (proc.annual_rate is not None and proc.term_periods and proc.payment_freq and proc.repayment_method):
        raise BusinessError("BAD_REQUEST", "缺少 利率/期数/频率/方式，无法生成还款计划", 422)

    # 1) 放款入金（NF1 幂等键）
    txn = CapitalTransaction(
        project_id=proc.project_id, source_type="金租融资", direction="IN",
        amount=actual_disbursement_amount, transaction_date=disbursement_date,
        leasing_process_id=proc.id, category="放款", idempotency_key=f"disburse:{proc.id}",
        note=note, created_by=disbursed_by,
    )
    db.add(txn)

    # 1.5) 资金置换：扫描项目中未置换的流贷/自有付款自动归还（v3.1）
    from app.services import audit_service as _audit
    from app.services import funding_service as fs
    replacements = fs.execute_replacement(
        db, project_id=proc.project_id, leasing_process_id=proc.id,
        disbursement_amount=actual_disbursement_amount,
        disbursement_date=disbursement_date, created_by=disbursed_by,
    )
    for fr in replacements:
        _audit.log(db, user_id=disbursed_by, action="SUPERSEDE", target_type="funding_replacement",
                   target_id=fr.id, after_json={"amount": str(fr.amount), "source": fr.source_type_replaced})

    # 2) 生成还款计划（复用 utils/repayment_plan）
    rows = generate_plan(
        principal=actual_disbursement_amount, annual_rate=proc.annual_rate,
        term_periods=proc.term_periods, payment_freq=proc.payment_freq,
        method=proc.repayment_method, disbursement_date=disbursement_date,
    )
    for r in rows:
        db.add(Repayment(
            leasing_process_id=proc.id, period=r.period, due_date=r.due_date,
            planned_principal=r.planned_principal, planned_interest=r.planned_interest, status="待还",
        ))

    # 3) 更新申请
    proc.actual_disbursement_amount = actual_disbursement_amount
    proc.disbursement_date = disbursement_date
    proc.status = "已放款"
    proc.plan_generated = True
    db.flush()
    _audit.log(db, user_id=disbursed_by, action="DISBURSE", target_type="leasing_process",
               target_id=proc.id, after_json={"amount": str(actual_disbursement_amount), "periods": len(rows)})
    from app.services import workflow_service as _wf
    _wf.after_action(db, proc.project_id)
    return proc, txn, len(rows)
