"""客户确认单 Service。"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.billing import Billing
from app.models.service_confirmation import ServiceConfirmation


def create_confirmation(db: Session, *, billing_id: uuid.UUID, sales_order_id: uuid.UUID,
                        period_label: str, created_by: uuid.UUID | None = None) -> ServiceConfirmation:
    # 一个 billing 只能有一个确认单（唯一约束在 billing_id 上）
    existing = db.execute(
        select(ServiceConfirmation).where(ServiceConfirmation.billing_id == billing_id)
    ).scalar_one_or_none()
    if existing:
        raise BusinessError("DUPLICATE", "该计费记录已有确认单", 409)

    sc = ServiceConfirmation(
        billing_id=billing_id, sales_order_id=sales_order_id,
        period_label=period_label, created_by=created_by,
    )
    db.add(sc)
    db.flush()
    return sc


def get_confirmation(db: Session, sc_id: uuid.UUID) -> ServiceConfirmation | None:
    return db.get(ServiceConfirmation, sc_id)


def list_confirmations(db: Session, *, sales_order_id: uuid.UUID | None = None,
                       status: str | None = None, skip=0, limit=100):
    stmt = select(ServiceConfirmation).where(ServiceConfirmation.deleted_at.is_(None))
    if sales_order_id:
        stmt = stmt.where(ServiceConfirmation.sales_order_id == sales_order_id)
    if status:
        stmt = stmt.where(ServiceConfirmation.status == status)
    stmt = stmt.order_by(ServiceConfirmation.created_at.desc()).offset(skip).limit(limit)
    return db.execute(stmt).scalars().all()


def confirm(db: Session, sc: ServiceConfirmation, *,
            confirmed_by_customer: str, confirmed_at=None, operator_id=None) -> ServiceConfirmation:
    """客户确认。"""
    from datetime import date
    if sc.status != "待确认":
        raise BusinessError("STATE_ERROR", f"当前状态 {sc.status} 不允许确认", 409)
    sc.status = "已确认"
    sc.confirmed_by_customer = confirmed_by_customer
    sc.confirmed_at = confirmed_at or date.today()
    # 同步更新 billings.confirmation_status
    billing = db.get(Billing, sc.billing_id)
    if billing:
        billing.confirmation_status = "已确认"
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="CONFIRM_UPLOAD", target_type="service_confirmation",
               target_id=sc.id, after_json={"customer": confirmed_by_customer})
    from app.services import workflow_service as _wf
    from app.models.sales_order import SalesOrder
    _so = db.get(SalesOrder, sc.sales_order_id)
    if _so:
        _wf.after_action(db, _so.project_id)
    return sc


def dispute(db: Session, sc: ServiceConfirmation, reason: str) -> ServiceConfirmation:
    """标记有争议。"""
    sc.status = "有争议"
    sc.dispute_reason = reason
    billing = db.get(Billing, sc.billing_id)
    if billing:
        billing.confirmation_status = "有争议"
    db.flush()
    return sc
