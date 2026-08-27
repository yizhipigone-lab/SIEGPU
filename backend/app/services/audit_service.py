"""审计日志服务 — 敏感业务操作留痕（C4 修复）。

用法一（声明式，#4 架构深化）：装饰 service 写函数，函数成功返回后自动留痕：
    from app.services.audit_service import audited

    @audited(action="CAPITAL_TXN", target_type="capital_transaction",
             fields=["source_type", "direction", "amount"])
    def record_transaction(db, *, created_by, **kw) -> CapitalTransaction: ...

用法二（函数体直调，计算型 payload / 多实体 / 关联实体目标的场景保留）：
    from app.services import audit_service as audit
    audit.log(db, user_id=actor, action="DISBURSE", target_type="leasing_process",
              target_id=proc.id, after_json={"amount": disbursement_amount})
"""
import functools
import inspect
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.user import AuditLog

# actor 参数名探取链（按序取第一个非 None 值；全缺记 NULL）
_ACTOR_PARAM_NAMES = ("actor_id", "user_id", "created_by", "operator_id",
                      "approved_by", "reversed_by", "returned_by", "disbursed_by",
                      "reconciled_by")


def _snapshot(entity, fields: Sequence[str]) -> dict:
    return {f: (str(getattr(entity, f)) if getattr(entity, f, None) is not None else None)
            for f in fields}


def audited(action: str, target_type: str, fields: Sequence[str] = (), *,
            update_arg: str | None = None):
    """声明式审计装饰器（#4 架构深化）。

    约定被装饰函数：签名含 db；返回目标 ORM 实体（或 None——不记审计）。
    - actor：按 _ACTOR_PARAM_NAMES 探取参数，不再逐函数手传
    - target_id：默认取返回实体 id；update_arg 给定时改取该参数实体
      （update 场景：调用前已持久化 → 先抓 fields 的 before 快照）
    - after_json：fields 声明字段的 str() 快照（Decimal/date 安全序列化）
    只 add 不 flush——随业务行同一 commit 原子提交（沿用 endpoint commit 铁律）。
    函数抛异常不落审计（审计只记成功操作）。
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            bound.apply_defaults()
            db = bound.arguments.get("db")
            actor = next((bound.arguments[n] for n in _ACTOR_PARAM_NAMES
                          if bound.arguments.get(n) is not None), None)
            update_entity = (bound.arguments.get(update_arg)
                             if update_arg is not None else None)
            before = None
            if update_entity is not None:
                try:  # update 场景：实体已持久化才抓 before 快照（新建/纯对象跳过）
                    from sqlalchemy import inspect as sa_inspect
                    state = sa_inspect(update_entity)
                    if state is not None and state.persistent:
                        before = _snapshot(update_entity, fields)
                except Exception:  # noqa: BLE001 —— 非 ORM 实体无持久化态，跳过 before
                    pass
            result = fn(*args, **kwargs)
            entity = update_entity if update_entity is not None else result
            if entity is not None and db is not None:
                log(db, user_id=actor, action=action, target_type=target_type,
                    target_id=entity.id, before_json=before,
                    after_json=_snapshot(entity, fields))
            return result
        return wrapper
    return deco


def log(db: Session, *, user_id: uuid.UUID | None, action: str,
        target_type: str, target_id: uuid.UUID | None = None,
        before_json: dict | None = None, after_json: dict | None = None,
        request_id: str | None = None, ip: str | None = None):
    """写一条审计日志。同事务内调用，随业务 commit 原子提交。
    #4：不再查库校验 user_id（N+1）——actor 由调用方/装饰器从参数取得，
    非法值由 FK 约束兜底（认证链保证 user_id 恒有效）。"""
    entry = AuditLog(
        user_id=user_id, action=action, entity_type=target_type,
        entity_id=target_id, before_json=before_json, after_json=after_json,
        request_id=request_id, ip=ip, at=datetime.utcnow(),
    )
    db.add(entry)
    # 不 flush——由调用方的 db.flush() 或 endpoint commit 统一提交
