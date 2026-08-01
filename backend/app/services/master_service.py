"""主数据通用 CRUD（list/create/update/soft-delete）。软删除后默认查询自动过滤。"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError


def list_entities(db: Session, model):
    return db.execute(select(model)).scalars().all()


def get_entity_or_404(db: Session, model, eid):
    obj = db.get(model, eid)
    if not obj or obj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "记录不存在", 404)
    return obj


def create_entity(db: Session, model, data: dict):
    obj = model(**data)
    db.add(obj)
    db.flush()
    return obj


def update_entity(db: Session, model, eid, data: dict):
    obj = get_entity_or_404(db, model, eid)
    for k, v in data.items():
        if v is not None and hasattr(obj, k):
            setattr(obj, k, v)
    db.flush()
    return obj


def soft_delete_entity(db: Session, model, eid):
    obj = get_entity_or_404(db, model, eid)
    obj.deleted_at = datetime.now(timezone.utc)
    db.flush()
    return obj
