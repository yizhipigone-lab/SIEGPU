"""审计日志服务 — 敏感业务操作留痕（C4 修复）。

用法：各 service 在关键操作 db.flush() 后调用：
    from app.services import audit_service as audit
    audit.log(db, user_id=actor, action="DISBURSE", target_type="leasing_process",
              target_id=proc.id, after_json={"amount": disbursement_amount})
"""
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.user import AuditLog


def log(db: Session, *, user_id: uuid.UUID | None, action: str,
        target_type: str, target_id: uuid.UUID | None = None,
        before_json: dict | None = None, after_json: dict | None = None,
        request_id: str | None = None, ip: str | None = None):
    """写一条审计日志。同事务内调用，随业务 commit 原子提交。"""
    # 校验 user_id 有效
    if user_id is not None:
        from app.models.user import User
        if not db.get(User, user_id):
            import logging
            logging.getLogger(__name__).warning(
                "audit_log: user_id=%s not found, logging with NULL (action=%s, target=%s/%s)",
                user_id, action, target_type, target_id)
            user_id = None  # 降级为 NULL 而非静默跳过
    entry = AuditLog(
        user_id=user_id, action=action, entity_type=target_type,
        entity_id=target_id, before_json=before_json, after_json=after_json,
        request_id=request_id, ip=ip, at=datetime.utcnow(),
    )
    db.add(entry)
    # 不 flush——由调用方的 db.flush() 或 endpoint commit 统一提交
