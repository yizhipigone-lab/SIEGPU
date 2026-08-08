"""验收记录 Service — 采购验收 + 销售验收。"""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.acceptance import AcceptanceRecord


def create_acceptance(db: Session, *, project_id: uuid.UUID, acceptance_type: str,
                      order_id: uuid.UUID | None = None, sales_order_id: uuid.UUID | None = None,
                      inspector: str | None = None, quantity_accepted: int = 0,
                      quantity_rejected: int = 0, notes: str | None = None) -> AcceptanceRecord:
    # 条件约束校验 [M9]
    if acceptance_type == "采购验收" and not order_id:
        raise BusinessError("VALIDATION_ERROR", "采购验收必须关联采购订单(order_id)", 422)
    if acceptance_type == "销售验收" and not sales_order_id:
        raise BusinessError("VALIDATION_ERROR", "销售验收必须关联销售订单(sales_order_id)", 422)

    ar = AcceptanceRecord(
        project_id=project_id, acceptance_type=acceptance_type,
        order_id=order_id, sales_order_id=sales_order_id,
        inspector=inspector, acceptance_date=date.today(),
        quantity_accepted=quantity_accepted, quantity_rejected=quantity_rejected,
        notes=notes,
    )
    db.add(ar)
    db.flush()
    return ar


def get_acceptance(db: Session, ar_id: uuid.UUID) -> AcceptanceRecord | None:
    return db.get(AcceptanceRecord, ar_id)


def list_acceptances(db: Session, *, project_id: uuid.UUID | None = None,
                     acceptance_type: str | None = None, skip=0, limit=100):
    stmt = select(AcceptanceRecord).where(AcceptanceRecord.deleted_at.is_(None))
    if project_id:
        stmt = stmt.where(AcceptanceRecord.project_id == project_id)
    if acceptance_type:
        stmt = stmt.where(AcceptanceRecord.acceptance_type == acceptance_type)
    stmt = stmt.order_by(AcceptanceRecord.created_at.desc()).offset(skip).limit(limit)
    return db.execute(stmt).scalars().all()


def approve_acceptance(db: Session, ar: AcceptanceRecord, *,
                       quantity_accepted: int | None = None,
                       quantity_rejected: int | None = None,
                       acceptance_date: date | None = None,
                       approved_by=None) -> AcceptanceRecord:
    """验收通过。"""
    if ar.status != "待验收" and ar.status != "验收中":
        raise BusinessError("STATE_ERROR", f"当前状态 {ar.status} 不允许验收通过", 409)
    ar.status = "已通过"
    if quantity_accepted is not None:
        ar.quantity_accepted = quantity_accepted
    if quantity_rejected is not None:
        ar.quantity_rejected = quantity_rejected
    if acceptance_date:
        ar.acceptance_date = acceptance_date
    else:
        ar.acceptance_date = date.today()
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=approved_by, action="ACCEPT_APPROVE", target_type="acceptance_record",
               target_id=ar.id, after_json={"status": "已通过", "type": ar.acceptance_type,
               "accepted": ar.quantity_accepted, "rejected": ar.quantity_rejected})
    from app.services import workflow_service as _wf
    _wf.after_action(db, ar.project_id)
    return ar


def reject_acceptance(db: Session, ar: AcceptanceRecord, reason: str, rejected_by=None) -> AcceptanceRecord:
    """验收驳回。"""
    if ar.status not in ("待验收", "验收中"):
        raise BusinessError("STATE_ERROR", f"当前状态 {ar.status} 不允许驳回", 409)
    ar.status = "已驳回"
    ar.rejection_reason = reason
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=rejected_by, action="ACCEPT_APPROVE", target_type="acceptance_record",
               target_id=ar.id, after_json={"status": "已驳回", "reason": reason})
    return ar
