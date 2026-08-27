"""只读工具层（VERA data_tools.py 的 ERP 版）：封装现有 services，LLM 绝不直接碰 SQL。

- 每个工具独立 try/except 由调用方（fastpath._safe / agent loop）包住，挂了标【缺】不拖死其他源。
- 返回全部为 JSON 可序列化的 dict/list（Decimal → float(q2)，date → str）。
- 写工具 P0 不开放（用户拍板），prompts 铁律 3 已声明只读。
"""
from __future__ import annotations

# 用户上下文传递：contextvars 在 StreamingResponse 的 threadpool 迭代中跨 yield 丢失
# （2026-08-27 e2e 实测），改为 call_tool 显式注入 user（needs_user 标记的工具才收）。

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import Invoice
from app.models.leasing import LeasingProcess
from app.models.project import Contract, Project
from app.models.repayment import Repayment
from app.services.assistant import datadict
from app.services.assistant.query import query_data


def _f(v) -> float:
    return float(Decimal(v or 0))


# ---------------------------------------------------------------- 经营看板

def get_business_board(db: Session) -> dict:
    """Dashboard 同款四块：核心指标 / 待办中心 / 资金预测 / EBS 状态。"""
    from app.services import business_board_service
    return business_board_service.business_board(db)


# ---------------------------------------------------------------- 资金池

def get_capital_position(db: Session) -> dict:
    """资金池总览：总余额 + 分池 + 分项目头寸。"""
    from app.services import capital_service
    return {
        "summary": capital_service.pool_summary(db),
        "by_project": capital_service.pool_by_project(db),
    }


# ---------------------------------------------------------------- 项目

def search_projects(db: Session, name: str) -> list[dict]:
    """按名称模糊查项目（ILIKE），返回 id/名称/状态/客户。"""
    rows = db.execute(
        select(Project).where(Project.name.ilike(f"%{name}%")).limit(10)
    ).scalars().all()
    return [{"id": str(p.id), "name": p.name, "code": p.code, "status": p.status}
            for p in rows]


def get_project_overview(db: Session, project_name: str) -> dict | None:
    """项目总览：关系图谱（合同/订单/设备/资金聚合）+ 流程节点。名称不唯一返回候选。"""
    hits = search_projects(db, project_name)
    if not hits:
        return None
    if len(hits) > 1:
        return {"ambiguous": True, "candidates": hits}
    from app.services import project_service, workflow_service
    pid = hits[0]["id"]
    rel = project_service.project_relationships(db, pid) or {}
    wf = workflow_service.get_workflow(db, pid)
    steps = []
    if wf and isinstance(wf.steps, list):
        steps = [{"seq": s.get("seq"), "name": s.get("name"), "status": s.get("status")}
                 for s in wf.steps]
    return {
        "project": hits[0],
        "relationships": rel,
        "workflow": {"current_step": wf.current_step, "status": wf.status, "steps": steps} if wf else None,
    }


def get_workflow_status(db: Session, project_name: str) -> dict | None:
    """项目流程卡在哪个节点。"""
    hits = search_projects(db, project_name)
    if not hits:
        return None
    if len(hits) > 1:
        return {"ambiguous": True, "candidates": hits}
    from app.services import workflow_service
    wf = workflow_service.get_workflow(db, hits[0]["id"])
    if not wf:
        return {"project": hits[0], "workflow": None, "note": "该项目尚未生成流程实例"}
    steps = [{"seq": s.get("seq"), "name": s.get("name"), "status": s.get("status"),
              "role": s.get("doer_role") or s.get("role")}
             for s in (wf.steps if isinstance(wf.steps, list) else [])]
    return {"project": hits[0], "current_step": wf.current_step,
            "status": wf.status, "steps": steps}


# ---------------------------------------------------------------- 还款

def list_due_repayments(db: Session, days: int = 30) -> list[dict]:
    """逾期未还 + 未来 N 天临期还款（关联金租流程 → 项目名）。"""
    today = date.today()
    horizon = today + timedelta(days=days)
    rows = db.execute(
        select(Repayment, LeasingProcess.project_id)
        .join(LeasingProcess, LeasingProcess.id == Repayment.leasing_process_id)
        .where(Repayment.status == "待还", Repayment.due_date <= horizon)
        .order_by(Repayment.due_date)
        .limit(100)
    ).all()
    proj_names = {str(p.id): p.name for p in db.execute(select(Project)).scalars().all()}
    out = []
    for r, pid in rows:
        out.append({
            "project": proj_names.get(str(pid), str(pid)),
            "period": r.period,
            "due_date": str(r.due_date),
            "planned_principal": _f(r.planned_principal),
            "planned_interest": _f(r.planned_interest),
            "overdue": r.due_date < today,
        })
    return out


# ---------------------------------------------------------------- 发票

def get_invoice_status(db: Session, contract_no: str | None = None,
                       project_name: str | None = None) -> list[dict] | None:
    """合同开票进度：合同额（含税优先）/ 已开 / 可用余额 / 超开风险。无过滤条件 → None（防全表）。"""
    q = select(Contract)
    if contract_no:
        q = q.where(Contract.contract_no.ilike(f"%{contract_no}%"))
    elif project_name:
        proj_ids = [h["id"] for h in search_projects(db, project_name)]
        if not proj_ids:
            return None
        q = q.where(Contract.project_id.in_(proj_ids))
    else:
        return None
    contracts = db.execute(q.limit(20)).scalars().all()
    out = []
    for c in contracts:
        invoiced = db.execute(
            select(func.coalesce(func.sum(Invoice.amount), 0)).where(
                Invoice.contract_id == c.id, Invoice.status != "已红冲",
                Invoice.deleted_at.is_(None))
        ).scalar() or Decimal(0)
        total = c.amount_incl_tax if c.amount_incl_tax is not None else c.amount
        available = Decimal(total) - Decimal(invoiced)
        out.append({
            "contract_no": c.contract_no, "type": c.type, "status": c.status,
            "contract_amount": _f(total),
            "invoiced": _f(invoiced),
            "available": _f(available),
            "over_invoice_risk": available <= 0,
        })
    return out


# ---------------------------------------------------------------- 预警 / 对账

def list_alerts(db: Session) -> list[dict]:
    """当前触发的全部预警（alert_service 实时计算，含级别/编码/说明）。"""
    from app.services import alert_service
    return alert_service.compute_alerts(db)


def get_reconciliation_diffs(db: Session) -> dict:
    """三流对账差异摘要（销售链/采购链/三流勾稽差异）。"""
    from app.services import reconciliation_service
    return {
        "sales_chain": reconciliation_service.dim1_sales_chain(db)[:20],
        "purchase_chain": reconciliation_service.dim2_purchase_chain(db)[:20],
        "flow_diffs": reconciliation_service.dim7_flow_diffs(db)[:20],
    }


# ---------------------------------------------------------------- 实体计数 / 订单摘要

def get_entity_counts(db: Session) -> dict:
    """核心实体计数一览：项目/合同(购销)/采购订单/销售订单/设备/资产/发票/还款计划。

    用户反馈驱动（2026-08-27）：「有多少张采购订单」这类最朴素的问题，
    看板指标里没有，必须有专门的计数工具兜底。"""
    from app.models.asset import Asset
    from app.models.delivery import Order
    from app.models.device import Device
    from app.models.sales_order import SalesOrder

    def cnt(model, *conds) -> int:
        return int(db.execute(
            select(func.count(model.id)).where(*conds)).scalar() or 0)

    return {
        "projects": cnt(Project),
        "contracts_sales": cnt(Contract, Contract.type == "SALES"),
        "contracts_purchase": cnt(Contract, Contract.type == "PURCHASE"),
        "purchase_orders": cnt(Order),
        "sales_orders": cnt(SalesOrder),
        "devices": cnt(Device),
        "assets": cnt(Asset),
        "invoices": cnt(Invoice),
        "repayment_plans_pending": cnt(Repayment, Repayment.status == "待还"),
    }


def get_order_summary(db: Session, project_name: str | None = None) -> dict:
    """订单摘要：采购/销售订单数量 + 按状态分组 + 最近 10 条。可按项目名过滤。"""
    from app.models.delivery import Order
    from app.models.sales_order import SalesOrder

    proj_ids = None
    if project_name:
        proj_ids = [h["id"] for h in search_projects(db, project_name)]
        if not proj_ids:
            return {"found": False, "note": f"没有名称含「{project_name}」的项目"}

    def summarize(model, label):
        q = select(model)
        if proj_ids is not None and hasattr(model, "project_id"):
            q = q.where(model.project_id.in_(proj_ids))
        total = int(db.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        by_status = {s: int(n) for s, n in db.execute(
            select(model.status, func.count()).group_by(model.status)
        ).all()} if hasattr(model, "status") else {}
        recent = [{
            "id": str(o.id), "status": getattr(o, "status", None),
            "created_at": str(getattr(o, "created_at", ""))[:10],
        } for o in db.execute(q.order_by(model.created_at.desc()).limit(10)).scalars().all()]
        return {"label": label, "total": total, "by_status": by_status, "recent": recent}

    return {"found": True,
            "purchase_orders": summarize(Order, "采购订单"),
            "sales_orders": summarize(SalesOrder, "销售订单")}


# ---------------------------------------------------------------- 指引知识库

def search_guide(query: str) -> list[dict]:
    """新手流程指引知识库检索（不需要 db）。"""
    from app.services.assistant import kb
    return kb.search(query, top_k=3)


# ---------------------------------------------------------------- 工具注册表（agent loop 用）
# schema 为 OpenAI function calling 格式；handler 统一签名为 (db, **kwargs)

TOOL_REGISTRY: dict[str, dict] = {
    "get_business_board": {
        "desc": "经营总览看板：核心指标（合同额/已回款/已开票/融资余额/资金池余额/设备点亮数）、待办中心、资金预测",
        "params": {"type": "object", "properties": {}, "required": []},
        "handler": lambda db: get_business_board(db),
    },
    "get_capital_position": {
        "desc": "资金池头寸：总余额、分池（自有/金租/银行/预付）、分项目净头寸与可调余额",
        "params": {"type": "object", "properties": {}, "required": []},
        "handler": lambda db: get_capital_position(db),
    },
    "search_projects": {
        "desc": "按名称模糊搜索项目，返回项目 id/名称/状态",
        "params": {"type": "object", "properties": {
            "name": {"type": "string", "description": "项目名称关键词"}}, "required": ["name"]},
        "handler": lambda db, name: search_projects(db, name),
    },
    "get_project_overview": {
        "desc": "项目总览：合同/订单/设备/资金聚合关系 + 当前流程节点",
        "params": {"type": "object", "properties": {
            "project_name": {"type": "string", "description": "项目名称（可模糊）"}}, "required": ["project_name"]},
        "handler": lambda db, project_name: get_project_overview(db, project_name),
    },
    "get_workflow_status": {
        "desc": "项目流程进度：当前走到第几步、每步状态与负责角色",
        "params": {"type": "object", "properties": {
            "project_name": {"type": "string", "description": "项目名称（可模糊）"}}, "required": ["project_name"]},
        "handler": lambda db, project_name: get_workflow_status(db, project_name),
    },
    "list_due_repayments": {
        "desc": "逾期未还 + 未来 N 天临期还款清单（项目/期次/到期日/计划本息）",
        "params": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "临期天数窗口，默认 30"}}, "required": []},
        "handler": lambda db, days=30: list_due_repayments(db, days),
    },
    "get_invoice_status": {
        "desc": "合同开票进度：合同额/已开票/可用余额/超开风险（按合同号或项目名过滤，必填其一）",
        "params": {"type": "object", "properties": {
            "contract_no": {"type": "string", "description": "合同号关键词"},
            "project_name": {"type": "string", "description": "项目名称关键词"}}, "required": []},
        "handler": lambda db, contract_no=None, project_name=None: get_invoice_status(
            db, contract_no=contract_no, project_name=project_name),
    },
    "list_alerts": {
        "desc": "当前触发的预警列表：还款逾期/资金不足/放款延迟/合同到期/流程停滞等，含级别",
        "params": {"type": "object", "properties": {}, "required": []},
        "handler": lambda db: list_alerts(db),
    },
    "get_reconciliation_diffs": {
        "desc": "三流（物流/票据流/资金流）对账差异摘要",
        "params": {"type": "object", "properties": {}, "required": []},
        "handler": lambda db: get_reconciliation_diffs(db),
    },
    "get_entity_counts": {
        "desc": "核心实体计数：项目/销售合同/采购合同/采购订单/销售订单/设备/资产/发票/待还还款计划各有多少。问「有多少/几张/几个 X」类计数问题优先用它",
        "params": {"type": "object", "properties": {}, "required": []},
        "handler": lambda db: get_entity_counts(db),
    },
    "get_order_summary": {
        "desc": "订单摘要：采购订单与销售订单的数量、按状态分组、最近订单。可按项目名过滤。问「多少张采购订单」「订单情况」用它",
        "params": {"type": "object", "properties": {
            "project_name": {"type": "string", "description": "可选，项目名称关键词"}}, "required": []},
        "handler": lambda db, project_name=None: get_order_summary(db, project_name),
    },
    "describe_schema": {
        "desc": "数据字典：看系统里有哪些业务实体（项目/合同/订单/设备/计费/发票/还款/资金流水/金租流程…）及其字段含义。遇到陌生问题先查它，再用 query_data 自己组条件找答案",
        "params": {"type": "object", "properties": {
            "entity": {"type": "string", "description": "可选，实体名（如 orders/devices）；不传则返回全部实体概览"}}, "required": []},
        "handler": lambda db, entity=None: datadict.describe(entity),
    },
    "query_data": {
        "desc": "通用只读查询：对白名单业务表组合条件/聚合/排序查数。filters=[{field,op(eq|ne|like|gt|ge|lt|le|in|isnull),value}]，metrics=[{func:count|sum|avg,field}]，group_by=[字段]，limit<=100。任何「多少/哪些/列表/汇总」类长尾问题用它自己查，不要说查不到",
        "params": {"type": "object", "properties": {
            "entity": {"type": "string", "description": "实体名（见 describe_schema）"},
            "filters": {"type": "array", "items": {"type": "object"}},
            "fields": {"type": "array", "items": {"type": "string"}},
            "group_by": {"type": "array", "items": {"type": "string"}},
            "metrics": {"type": "array", "items": {"type": "object"}},
            "order_by": {"type": "string", "description": "如 'created_at desc'"},
            "limit": {"type": "integer", "description": "默认 20，最大 100"}},
            "required": ["entity"]},
        "handler": lambda db, entity, filters=None, fields=None, group_by=None,
                          metrics=None, order_by=None, limit=20: query_data(
            db, entity, filters=filters, fields=fields, group_by=group_by,
            metrics=metrics, order_by=order_by, limit=limit),
    },
    "request_record_income": {
        "desc": "生成「登记回款」预览确认卡（不执行！需用户在界面上点确认）。参数：project_name 项目名（必填）、amount 金额元（必填>0）、transaction_date 日期YYYY-MM-DD（可选默认今天）、note 备注（可选）",
        "params": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "amount": {"type": "number"},
            "transaction_date": {"type": "string"}, "note": {"type": "string"}},
            "required": ["project_name", "amount"]},
        "handler": lambda db, user, project_name, amount, transaction_date=None, note=None: _write_dry(
            db, user, "record_income", {"project_name": project_name, "amount": amount,
                                  "transaction_date": transaction_date, "note": note}),
        "write_action": "record_income",
        "needs_user": True,
    },
    "request_draft_billing": {
        "desc": "生成「计费草稿」预览确认卡（不执行！需用户确认）。参数：device_sn 设备序列号（必填）、period_index 计费期数（必填≥1）、billing_date（可选）",
        "params": {"type": "object", "properties": {
            "device_sn": {"type": "string"}, "period_index": {"type": "integer"},
            "billing_date": {"type": "string"}}, "required": ["device_sn", "period_index"]},
        "handler": lambda db, user, device_sn, period_index, billing_date=None: _write_dry(
            db, user, "draft_billing", {"device_sn": device_sn, "period_index": period_index,
                                  "billing_date": billing_date}),
        "write_action": "draft_billing",
        "needs_user": True,
    },
    "request_advance_step": {
        "desc": "生成「流程推进」预览确认卡（不执行！需用户确认）。参数：project_name（必填）、seq 步骤号（可选默认当前步）、note 备注（可选）",
        "params": {"type": "object", "properties": {
            "project_name": {"type": "string"}, "seq": {"type": "integer"}, "note": {"type": "string"}},
            "required": ["project_name"]},
        "handler": lambda db, user, project_name, seq=None, note=None: _write_dry(
            db, user, "advance_step", {"project_name": project_name, "seq": seq, "note": note}),
        "write_action": "advance_step",
        "needs_user": True,
    },
    "request_allocate_funds": {
        "desc": "生成「资金调配」预览确认卡（不执行！需用户确认）。参数：from_project_name/to_project_name（必填）、amount（必填>0）、allocation_date/expected_return_date/reason（可选）",
        "params": {"type": "object", "properties": {
            "from_project_name": {"type": "string"}, "to_project_name": {"type": "string"},
            "amount": {"type": "number"}, "allocation_date": {"type": "string"},
            "expected_return_date": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["from_project_name", "to_project_name", "amount"]},
        "handler": lambda db, user, from_project_name, to_project_name, amount,
                              allocation_date=None, expected_return_date=None, reason=None: _write_dry(
            db, user, "allocate_funds", {"from_project_name": from_project_name, "to_project_name": to_project_name,
                                   "amount": amount, "allocation_date": allocation_date,
                                   "expected_return_date": expected_return_date, "reason": reason}),
        "write_action": "allocate_funds",
        "needs_user": True,
    },
    "save_cognition": {
        "desc": "保存长期认知（助手自身数据，非业务单据）：用户说「记住：我说X指Y」时用它。kind=entity_alias(实体别名)/glossary_pref(口径偏好)/query_hint(查询习惯)。value 里不许带金额数字",
        "params": {"type": "object", "properties": {
            "key": {"type": "string", "description": "检索键，如「七号项目」"},
            "value": {"type": "string", "description": "认知内容，如「指项目 商机5090」"},
            "kind": {"type": "string", "description": "entity_alias/glossary_pref/query_hint"}}, "required": ["key", "value", "kind"]},
        "handler": lambda db, user, key, value, kind: _cog_save(db, user, key, value, kind),
        "needs_user": True,
    },
    "list_cognition": {
        "desc": "查看我的长期认知列表（助手自身数据）：已记住的别名/口径偏好，可按关键词过滤",
        "params": {"type": "object", "properties": {
            "query": {"type": "string", "description": "可选关键词过滤"}}, "required": []},
        "handler": lambda db, user, query=None: _cog_list(db, user, query),
        "needs_user": True,
    },
    "forget_cognition": {
        "desc": "删除一条我的长期认知（助手自身数据）：用户说「忘掉XX」时用它",
        "params": {"type": "object", "properties": {
            "id": {"type": "string", "description": "认知条目 id（从 list_cognition 拿）"}}, "required": ["id"]},
        "handler": lambda db, user, id: _cog_forget(db, user, id),
        "needs_user": True,
    },
    "search_guide": {
        "desc": "新手流程指引知识库：怎么操作某流程、术语是什么意思、概念区别（不需要业务数据）",
        "params": {"type": "object", "properties": {
            "query": {"type": "string", "description": "指引问题"}}, "required": ["query"]},
        "handler": lambda db, query: search_guide(query),
    },
}


# ---------------------------------------------------------------- 认知工具（M-A；助手自身数据）

def _cog_save(db, user, key, value, kind):
    """保存认知：user 由 call_tool 显式注入（needs_user 工具）。"""
    from app.services.assistant import memory
    row, msg = memory.save_cognition(db, user.id, key, value, kind, source="user")
    return {"saved": row is not None, "message": msg, "id": str(row.id) if row else None}


def _cog_list(db, user, query=None):
    from sqlalchemy import select as _s
    from app.models.assistant import AssistantCognition
    rows = db.execute(_s(AssistantCognition).where(
        AssistantCognition.user_id == user.id)).scalars().all()
    out = [{"id": str(r.id), "kind": r.kind, "key": r.key, "value": r.value,
            "source": r.source, "usage_count": r.usage_count} for r in rows]
    if query:
        out = [o for o in out if query in o["key"] or query in o["value"]]
    return {"items": out}


def _cog_forget(db, user, id):
    import datetime as _dt
    import uuid as _u
    from sqlalchemy import select as _s
    from app.models.assistant import AssistantCognition
    try:
        row = db.execute(_s(AssistantCognition).where(
            AssistantCognition.id == _u.UUID(id),
            AssistantCognition.user_id == user.id)).scalars().first()
    except ValueError:
        return {"forgotten": False, "message": "id 格式不对"}
    if not row:
        return {"forgotten": False, "message": "没找到这条认知（只能删自己的）"}
    row.deleted_at = _dt.datetime.now(_dt.timezone.utc)
    db.flush()
    return {"forgotten": True, "message": f"已忘掉「{row.key}」"}


# ---------------------------------------------------------------- 写操作 dry-run 入口（M-C）
# 不变量：LLM 只有 dry_run 通道；execute 在 writes.py，仅由 /confirm 端点调用。

def _write_dry(db, user, action: str, params: dict):
    from app.services.assistant import writes
    return writes.dry_run(db, user, action, params or {})


def openai_tools() -> list[dict]:
    """OpenAI function calling 格式的工具声明。写工具只在白名单开放时暴露（不变量5：开关断电即隐身）。"""
    from app.services.assistant import writes
    enabled = set(writes.enabled_actions())
    out = []
    for name, spec in TOOL_REGISTRY.items():
        wa = spec.get("write_action")
        if wa and wa not in enabled:
            continue
        out.append({"type": "function",
                    "function": {"name": name, "description": spec["desc"],
                                 "parameters": spec["params"]}})
    return out


def call_tool(db: Session, name: str, args: dict, user=None):
    """agent loop 统一调用口；未知名称抛 KeyError；needs_user 工具显式收 user（无则结构化报错）。"""
    spec = TOOL_REGISTRY.get(name)
    if not spec:
        raise KeyError(f"未知工具: {name}")
    wa = spec.get("write_action")
    if wa:
        from app.services.assistant import writes
        if wa not in writes.enabled_actions():
            raise KeyError(f"写动作未开放: {name}")
    if spec.get("needs_user"):
        if user is None:
            return {"error": "该工具需要在对话中使用"}
        return spec["handler"](db, user, **(args or {}))
    return spec["handler"](db, **(args or {}))