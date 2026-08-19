"""操作留痕查询（前端单据详情「操作记录」tab）。只读，任何登录用户可见。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.models.user import AuditLog, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(
    entity_type: str = Query(...),
    entity_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("ADMIN", "FINANCE_DIRECTOR")),
) -> dict:
    stmt = select(AuditLog).where(AuditLog.entity_type == entity_type)
    if entity_id:
        try:
            eid = uuid.UUID(entity_id)
        except ValueError:
            return {"items": []}
        stmt = stmt.where(AuditLog.entity_id == eid)
    stmt = stmt.order_by(AuditLog.id.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()

    # 批量取用户显示名，避免 N+1
    uids = {r.user_id for r in rows if r.user_id}
    name_map: dict[uuid.UUID, str] = {}
    if uids:
        for u in db.execute(select(User).where(User.id.in_(uids))).scalars():
            name_map[u.id] = u.display_name

    items = [
        {
            "id": r.id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "user_name": name_map.get(r.user_id, "—"),
            "at": r.at.isoformat() if r.at else None,
        }
        for r in rows
    ]
    return {"items": items}
