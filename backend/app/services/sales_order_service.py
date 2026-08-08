"""销售订单 Service — CRUD。"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sales_order import SalesOrder


def create_sales_order(db: Session, *, project_id: uuid.UUID, contract_id: uuid.UUID,
                       equipment_model_id: uuid.UUID, quantity: int,
                       monthly_rent_per_unit, total_monthly_rent,
                       start_date=None, end_date=None, status="待交付", notes=None):
    so = SalesOrder(
        project_id=project_id, contract_id=contract_id,
        equipment_model_id=equipment_model_id, quantity=quantity,
        monthly_rent_per_unit=monthly_rent_per_unit,
        total_monthly_rent=total_monthly_rent,
        start_date=start_date, end_date=end_date,
        status=status, notes=notes,
    )
    db.add(so)
    db.flush()
    from app.services import workflow_service as _wf
    _wf.after_action(db, project_id)
    return so


def get_sales_order(db: Session, so_id: uuid.UUID) -> SalesOrder | None:
    return db.get(SalesOrder, so_id)


def list_sales_orders(db: Session, *, project_id: uuid.UUID | None = None, skip=0, limit=100):
    stmt = select(SalesOrder).where(SalesOrder.deleted_at.is_(None))
    if project_id:
        stmt = stmt.where(SalesOrder.project_id == project_id)
    stmt = stmt.order_by(SalesOrder.created_at.desc()).offset(skip).limit(limit)
    return db.execute(stmt).scalars().all()


def update_sales_order(db: Session, so: SalesOrder, **kwargs):
    for k, v in kwargs.items():
        if v is not None and hasattr(so, k):
            setattr(so, k, v)
    db.flush()
    return so
