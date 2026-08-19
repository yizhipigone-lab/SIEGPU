"""销售订单 Service — CRUD + W4 销售批次组合。"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.device import Device
from app.models.sales_order import SalesBatchDevice, SalesOrder


def create_sales_order(db: Session, *, project_id: uuid.UUID, contract_id: uuid.UUID,
                       equipment_model_id: uuid.UUID, quantity: int,
                       monthly_rent_per_unit, total_monthly_rent,
                       start_date=None, end_date=None, status="待交付", notes=None,
                       is_batch=False, batch_name=None):
    so = SalesOrder(
        project_id=project_id, contract_id=contract_id,
        equipment_model_id=equipment_model_id, quantity=quantity,
        monthly_rent_per_unit=monthly_rent_per_unit,
        total_monthly_rent=total_monthly_rent,
        start_date=start_date, end_date=end_date,
        status=status, notes=notes,
        is_batch=is_batch, batch_name=batch_name,
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


# ============================ W4：销售批次组合 ============================

def _active_sales_batch_row(db: Session, device_id: uuid.UUID) -> SalesBatchDevice | None:
    return db.execute(
        select(SalesBatchDevice).where(
            SalesBatchDevice.device_id == device_id,
            SalesBatchDevice.active.is_(True),
        )
    ).scalars().first()


def add_to_sales_batch(db: Session, *, device_id: uuid.UUID, sales_batch_id: uuid.UUID,
                       operator_id: uuid.UUID | None = None) -> SalesBatchDevice:
    """设备挂入销售批次（照采购侧 add_to_batch 模式）。守卫：销售批次存在 + 设备当前无 active 批次。"""
    d = db.get(Device, device_id)
    if not d or d.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "设备不存在", 404)
    batch = db.get(SalesOrder, sales_batch_id)
    if not batch or batch.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "销售批次不存在", 404)
    if not batch.is_batch:
        batch.is_batch = True
    existing = _active_sales_batch_row(db, device_id)
    if existing:
        raise BusinessError("DUPLICATE", "设备已在销售批次中，不能重复挂载", 409)
    bd = SalesBatchDevice(sales_batch_id=sales_batch_id, device_id=device_id,
                          action="加入", active=True, operated_by=operator_id)
    db.add(bd)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="device",
               target_id=d.id, after_json={"sales_batch_id": str(sales_batch_id), "batch_action": "加入"})
    return bd


def remove_from_sales_batch(db: Session, *, device_id: uuid.UUID,
                            operator_id: uuid.UUID | None = None) -> SalesBatchDevice:
    """设备移出销售批次。"""
    d = db.get(Device, device_id)
    if not d or d.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "设备不存在", 404)
    active = _active_sales_batch_row(db, device_id)
    if not active:
        raise BusinessError("NOT_FOUND", "设备当前不在任何销售批次中", 404)
    active.active = False
    out = SalesBatchDevice(sales_batch_id=active.sales_batch_id, device_id=device_id,
                           action="移出", active=False, operated_by=operator_id)
    db.add(out)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="device",
               target_id=d.id, after_json={"sales_batch_id": str(active.sales_batch_id), "batch_action": "移出"})
    return out


def list_sales_batch_devices(db: Session, sales_batch_id: uuid.UUID | None = None,
                             device_id: uuid.UUID | None = None):
    stmt = select(SalesBatchDevice).where(SalesBatchDevice.deleted_at.is_(None))
    if sales_batch_id:
        stmt = stmt.where(SalesBatchDevice.sales_batch_id == sales_batch_id)
    if device_id:
        stmt = stmt.where(SalesBatchDevice.device_id == device_id)
    stmt = stmt.order_by(SalesBatchDevice.created_at.desc())
    return db.execute(stmt).scalars().all()
