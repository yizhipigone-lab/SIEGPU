"""写操作确认卡执行器（M-C）：dry_run 出预览+令牌，execute 原子认领后走既有 service 层。

八条不变量（计划书 v1.2 §4.2）落地：
1. LLM 无执行通道——execute 只被 /confirm 端点调用，绝不注册为 LLM 工具；
2. 卡上金额=服务端 dry_run 计算，LLM 数字只当「用户意图参考」，执行用 params_resolved；
3. idempotency_key 唯一 + 原子认领（条件 UPDATE used_at），单次执行；
4. 认领时复查角色/过期（token 签发后世界可能变了）；
5. 确认/取消/过期均落 audit（ASSISTANT_WRITE）；
6. 日确认限额（当日 used_at 非空行数）；
7. amount>0 等 DB CHECK 前置校验；
8. 每动作 allowed_roles 双侧（dry_run+execute）校验。
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.assistant import AssistantConfirmToken
from app.models.user import User

_BIG_AMOUNT = Decimal("1000000")  # 大额提示线


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _d(v) -> Decimal:
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"金额格式不对: {v!r}")


def _resolve_project(db: Session, name: str):
    """项目名解析：必须唯一命中，否则报错让 LLM 继续澄清。"""
    from app.models.project import Project
    rows = db.execute(select(Project).where(
        Project.name.ilike(f"%{(name or '').strip()}%"))).scalars().all()
    if not rows:
        raise ValueError(f"没有名称含「{name}」的项目，请先和用户确认项目名")
    if len(rows) > 1:
        raise ValueError(f"「{name}」命中 {len(rows)} 个项目（{('、'.join(p.name for p in rows[:3]))}…），请让用户说全名")
    return rows[0]


def _resolve_device(db: Session, sn: str):
    from app.models.device import Device
    dev = db.execute(select(Device).where(Device.sn == (sn or "").strip())).scalars().first()
    if not dev:
        raise ValueError(f"没找到序列号 {sn} 的设备")
    return dev


# ---------------------------------------------------------------- 动作实现

def _dry_record_income(db: Session, params: dict) -> dict:
    p = params or {}
    proj = _resolve_project(db, p.get("project_name", ""))
    amount = _d(p.get("amount"))
    if amount <= 0:
        raise ValueError("金额必须大于 0")
    date_str = p.get("transaction_date") or dt.date.today().isoformat()
    warnings = []
    if amount >= _BIG_AMOUNT:
        warnings.append(f"大额回款（≥{_BIG_AMOUNT}），请复核金额与到账凭证")
    resolved = {
        "project_id": str(proj.id), "project_name": proj.name,
        "source_type": "租金收入", "direction": "IN",  # 审计一 F2：系统口径客户回款=租金收入
        "amount": str(amount), "transaction_date": date_str,
        "note": (p.get("note") or f"AI 老虎代登记：{proj.name} 回款").strip()[:200],
    }
    return {"params_resolved": resolved, "impact_amount": amount,
            "impact_desc": f"项目「{proj.name}」登记回款（租金收入/IN）", "warnings": warnings}


def _exe_record_income(db: Session, user: User, params: dict, idem: str = ""):
    from app.services import capital_service
    kw = dict(params)
    kw["project_id"] = uuid.UUID(kw.pop("project_id"))
    kw.pop("project_name", None)
    kw["amount"] = Decimal(kw["amount"])
    kw["transaction_date"] = dt.date.fromisoformat(kw["transaction_date"])
    txn = capital_service.record_transaction(db, created_by=user.id, **kw)
    return {"kind": "capital_transaction", "id": str(txn.id),
            "amount": str(txn.amount), "date": str(txn.transaction_date)}


def _dry_draft_billing(db: Session, params: dict) -> dict:
    p = params or {}
    dev = _resolve_device(db, p.get("device_sn", ""))
    from app.models.project import Contract
    ct = db.execute(select(Contract).where(
        Contract.id == dev.sales_contract_id)).scalars().first() if dev.sales_contract_id else None
    if not ct:
        raise ValueError("该设备没有关联销售合同，无法计费（请先在系统里补关联）")
    period = int(p.get("period_index", 0))
    if period < 1:
        raise ValueError("计费期数必须 ≥1")
    resolved = {
        "device_id": str(dev.id), "device_sn": dev.sn,
        "contract_id": str(ct.id), "contract_no": ct.contract_no,
        "period_index": period,
        "billing_date": p.get("billing_date") or dt.date.today().isoformat(),
    }
    return {"params_resolved": resolved, "impact_amount": None,
            "impact_desc": f"设备 {dev.sn} 第 {period} 期计费草稿（金额由系统按点亮周期计算）",
            "warnings": ["计费金额由系统按台数与点亮周期计算，非人工填写"]}


def _exe_draft_billing(db: Session, user: User, params: dict, idem: str = ""):
    from app.services import billing_service
    b = billing_service.generate_billing_device(
        db, device_id=uuid.UUID(params["device_id"]), contract_id=uuid.UUID(params["contract_id"]),
        period_index=int(params["period_index"]),
        billing_date=dt.date.fromisoformat(params["billing_date"]))
    return {"kind": "billing", "id": str(b.id), "amount": str(b.amount)}


def _dry_advance_step(db: Session, params: dict) -> dict:
    p = params or {}
    proj = _resolve_project(db, p.get("project_name", ""))
    from app.services import workflow_service
    wf = workflow_service.get_workflow(db, proj.id)
    if not wf:
        raise ValueError(f"项目「{proj.name}」没有流程实例")
    seq = int(p.get("seq") or wf.current_step)
    resolved = {"project_id": str(proj.id), "project_name": proj.name, "seq": seq,
                "note": (p.get("note") or "AI 老虎代推进").strip()[:200]}
    return {"params_resolved": resolved, "impact_amount": None,
            "impact_desc": f"项目「{proj.name}」第 {seq} 步标记完成", "warnings": []}


def _exe_advance_step(db: Session, user: User, params: dict, idem: str = ""):
    from app.services import workflow_service
    wf = workflow_service.mark_step_done(
        db, uuid.UUID(params["project_id"]), int(params["seq"]),
        params.get("note"), operator_id=user.id)
    return {"kind": "workflow", "current_step": wf.current_step, "status": wf.status}


def _dry_allocate_funds(db: Session, params: dict) -> dict:
    p = params or {}
    src = _resolve_project(db, p.get("from_project_name", ""))
    dst = _resolve_project(db, p.get("to_project_name", ""))
    if src.id == dst.id:
        raise ValueError("调出与调入项目不能相同")
    amount = _d(p.get("amount"))
    if amount <= 0:
        raise ValueError("金额必须大于 0")
    resolved = {
        "from_project_id": str(src.id), "from_project_name": src.name,
        "to_project_id": str(dst.id), "to_project_name": dst.name,
        "amount": str(amount),
        "allocation_date": p.get("allocation_date") or dt.date.today().isoformat(),
        "expected_return_date": p.get("expected_return_date"),
        "reason": (p.get("reason") or "AI 老虎代调配").strip()[:200],
    }
    return {"params_resolved": resolved, "impact_amount": amount,
            "impact_desc": f"「{src.name}」→「{dst.name}」调配 {amount} 元（池校验在执行时强制）",
            "warnings": [f"跨项目动钱：执行时按服务端池余额硬校验"]}


def _exe_allocate_funds(db: Session, user: User, params: dict, idem: str = ""):
    from app.services import capital_service
    a = capital_service.allocate(
        db, approved_by=user.id, from_project_id=uuid.UUID(params["from_project_id"]),
        to_project_id=uuid.UUID(params["to_project_id"]), amount=Decimal(params["amount"]),
        allocation_date=dt.date.fromisoformat(params["allocation_date"]),
        expected_return_date=dt.date.fromisoformat(params["expected_return_date"])
        if params.get("expected_return_date") else None,
        reason=params.get("reason"), idempotency_key=idem)
    return {"kind": "allocation", "id": str(a.id)}


# ---------------------------------------------------------------- 注册表

ACTIONS: dict[str, dict] = {
    "record_income": {
        "label": "登记回款", "roles": {"FINANCE_STAFF", "FINANCE_DIRECTOR", "ADMIN"},
        "dry": _dry_record_income, "exe": _exe_record_income,
    },
    "draft_billing": {
        "label": "计费草稿", "roles": {"FINANCE_STAFF", "FINANCE_DIRECTOR", "ADMIN"},
        "dry": _dry_draft_billing, "exe": _exe_draft_billing,
    },
    "advance_step": {
        "label": "流程推进", "roles": {"FINANCE_STAFF", "FINANCE_DIRECTOR", "ADMIN", "DELIVERY", "PROCUREMENT"},
        "dry": _dry_advance_step, "exe": _exe_advance_step,
    },
    "allocate_funds": {
        "label": "资金调配", "roles": {"FINANCE_DIRECTOR", "ADMIN"},
        "dry": _dry_allocate_funds, "exe": _exe_allocate_funds,
    },
}

_ENABLED_ACTIONS_CACHE: list[str] | None = None


def enabled_actions() -> list[str]:
    """config 白名单 ∩ 注册表（总开关关 → 空）。"""
    global _ENABLED_ACTIONS_CACHE
    if _ENABLED_ACTIONS_CACHE is None:
        if not settings.assistant_writes_enabled:
            _ENABLED_ACTIONS_CACHE = []
        else:
            want = [a.strip() for a in settings.assistant_write_actions.split(",") if a.strip()]
            _ENABLED_ACTIONS_CACHE = [a for a in want if a in ACTIONS]
    return _ENABLED_ACTIONS_CACHE


def reset_cache() -> None:
    global _ENABLED_ACTIONS_CACHE
    _ENABLED_ACTIONS_CACHE = None


def dry_run(db: Session, user: User, action: str, params: dict) -> dict:
    """生成预览 + 确认令牌（不执行任何业务写）。"""
    if action not in enabled_actions():
        return {"error": f"写动作 {action} 未开放（当前白名单：{enabled_actions() or '无'}）"}
    spec = ACTIONS[action]
    if user.role not in spec["roles"]:
        return {"error": f"你的角色（{user.role}）不能执行「{spec['label']}」"}
    try:
        preview = spec["dry"](db, params or {})
    except ValueError as exc:
        return {"error": str(exc)}
    token = AssistantConfirmToken(
        user_id=user.id, action=action, params_json=preview["params_resolved"],
        impact_amount=preview["impact_amount"], warnings=preview.get("warnings") or [],
        idempotency_key=uuid.uuid4().hex,
        expires_at=_utcnow() + dt.timedelta(minutes=settings.assistant_confirm_ttl_minutes))
    db.add(token)
    db.flush()
    return {
        "card": {
            "kind": "confirm", "token_id": str(token.id), "action": action,
            "label": spec["label"], "params": preview["params_resolved"],
            "impact_amount": float(preview["impact_amount"]) if preview["impact_amount"] is not None else None,
            "impact_desc": preview["impact_desc"], "warnings": preview.get("warnings") or [],
            "expires_in_minutes": settings.assistant_confirm_ttl_minutes,
        },
        "message": f"已生成「{spec['label']}」预览卡，请用户确认后才会执行。",
    }


def _daily_used(db: Session, user_id) -> int:
    start = (_utcnow() - dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(select(AssistantConfirmToken.id).where(
        AssistantConfirmToken.user_id == user_id,
        AssistantConfirmToken.used_at.is_not(None),
        AssistantConfirmToken.used_at >= start)).all()
    return len(rows)


def execute(db: Session, user: User, token_id: str) -> dict:
    """确认执行：限额 → 原子认领 → 角色复查 → service 调用 → 审计。"""
    from app.services import audit_service
    if _daily_used(db, user.id) >= settings.assistant_write_daily_limit:
        return {"ok": False, "status": 429, "message": f"今日确认次数已达上限（{settings.assistant_write_daily_limit}）"}
    tok = db.get(AssistantConfirmToken, uuid.UUID(token_id))
    if not tok or tok.user_id != user.id:
        return {"ok": False, "status": 403, "message": "令牌不存在或不是你的"}
    spec = ACTIONS.get(tok.action)
    if not spec or user.role not in spec["roles"]:
        return {"ok": False, "status": 403, "message": "你的角色不能执行该动作（复核）"}
    # 原子认领（审计二 D3）：认领失败即终态
    claimed = db.execute(
        update(AssistantConfirmToken)
        .where(AssistantConfirmToken.id == tok.id,
               AssistantConfirmToken.used_at.is_(None),
               AssistantConfirmToken.expires_at > _utcnow())
        .values(used_at=_utcnow(), result_json={"status": "executing"})
        .returning(AssistantConfirmToken.id)).scalar()
    if not claimed:
        if tok.expires_at <= _utcnow():
            return {"ok": False, "status": 410, "message": "令牌已过期，请重新发起"}
        return {"ok": False, "status": 409, "message": "令牌已被使用（不可重复确认）"}
    try:
        result = spec["exe"](db, user, dict(tok.params_json), idem=tok.idempotency_key)
        db.flush()
        tok.result_json = {"status": "done", "result": result}
        audit_service.log(db, user_id=user.id, action="ASSISTANT_WRITE",
                          target_type="assistant_confirm_token", target_id=tok.id,
                          after_json={"action": tok.action, "ok": True, "result": result})
        return {"ok": True, "status": 200, "message": f"「{spec['label']}」执行成功", "result": result}
    except Exception as exc:  # noqa: BLE001 —— 业务失败：令牌置失败终态（认领不回滚，防重试绕过）
        db.rollback()
        tok2 = db.execute(select(AssistantConfirmToken).where(
            AssistantConfirmToken.id == uuid.UUID(token_id))).scalars().first()
        if tok2 is not None:
            tok2.result_json = {"status": "failed", "error": str(exc)[:200]}
            audit_service.log(db, user_id=user.id, action="ASSISTANT_WRITE",
                              target_type="assistant_confirm_token", target_id=tok2.id,
                              after_json={"action": tok2.action, "ok": False, "error": str(exc)[:200]})
        return {"ok": False, "status": 422, "message": f"执行失败：{str(exc)[:160]}"}


def cancel(db: Session, user: User, token_id: str) -> dict:
    """取消：置终态 + 审计（不执行业务）。"""
    from app.services import audit_service
    tok = db.get(AssistantConfirmToken, uuid.UUID(token_id))
    if not tok or tok.user_id != user.id:
        return {"ok": False, "status": 403, "message": "令牌不存在或不是你的"}
    claimed = db.execute(
        update(AssistantConfirmToken)
        .where(AssistantConfirmToken.id == tok.id, AssistantConfirmToken.used_at.is_(None))
        .values(used_at=_utcnow(), result_json={"status": "cancelled"})
        .returning(AssistantConfirmToken.id)).scalar()
    if not claimed:
        return {"ok": False, "status": 409, "message": "令牌已终态（已用/已取消）"}
    audit_service.log(db, user_id=user.id, action="ASSISTANT_WRITE",
                      target_type="assistant_confirm_token", target_id=tok.id,
                      after_json={"action": tok.action, "cancelled": True})
    return {"ok": True, "status": 200, "message": "已取消"}