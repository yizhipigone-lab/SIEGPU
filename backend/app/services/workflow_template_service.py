"""流程模板 Service — CRUD。"""
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.exceptions import BusinessError
from app.models.workflow_template import WorkflowTemplate


def create_template(db: Session, *, name: str, description: str | None = None,
                    steps: list[dict], is_active: bool = True) -> WorkflowTemplate:
    tmpl = WorkflowTemplate(name=name, description=description, steps=steps, is_active=is_active)
    db.add(tmpl)
    db.flush()
    return tmpl


def list_templates(db: Session, *, active_only: bool = True) -> list[WorkflowTemplate]:
    stmt = select(WorkflowTemplate).where(WorkflowTemplate.deleted_at.is_(None))
    if active_only:
        stmt = stmt.where(WorkflowTemplate.is_active == True)
    stmt = stmt.order_by(WorkflowTemplate.created_at.asc())
    return db.execute(stmt).scalars().all()


def get_template(db: Session, tmpl_id: uuid.UUID) -> WorkflowTemplate | None:
    return db.get(WorkflowTemplate, tmpl_id)
