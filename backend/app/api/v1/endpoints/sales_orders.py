"""销售订单 API。"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.sales_order import (
    SalesBatchAssign,
    SalesBatchDeviceOut,
    SalesBatchRemove,
    SalesOrderCreate,
    SalesOrderOut,
    SalesOrderUpdate,
)
from app.services import sales_order_service as svc

router = APIRouter(prefix="/api/sales-orders", tags=["销售订单"])


@router.post("", response_model=SalesOrderOut, status_code=201)
def create_so(payload: SalesOrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    so = svc.create_sales_order(db, **payload.model_dump())
    db.commit()
    return SalesOrderOut.model_validate(so)


@router.get("", response_model=list[SalesOrderOut])
def list_sos(project_id: str | None = Query(None), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pid = UUID(project_id) if project_id else None
    return [SalesOrderOut.model_validate(s) for s in svc.list_sales_orders(db, project_id=pid)]


@router.get("/batch-devices", response_model=dict)
def list_batch_devices(sales_batch_id: UUID | None = None, device_id: UUID | None = None,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_sales_batch_devices(db, sales_batch_id=sales_batch_id, device_id=device_id)
    return {"items": [SalesBatchDeviceOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}


@router.post("/batch-assign", response_model=SalesBatchDeviceOut, status_code=201)
def batch_assign(payload: SalesBatchAssign, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bd = svc.add_to_sales_batch(db, device_id=payload.device_id,
                                sales_batch_id=payload.sales_batch_id, operator_id=user.id)
    db.commit()
    return SalesBatchDeviceOut.model_validate(bd)


@router.post("/batch-remove", response_model=SalesBatchDeviceOut)
def batch_remove(payload: SalesBatchRemove, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bd = svc.remove_from_sales_batch(db, device_id=payload.device_id, operator_id=user.id)
    db.commit()
    return SalesBatchDeviceOut.model_validate(bd)


@router.get("/{so_id}", response_model=SalesOrderOut)
def get_so(so_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.core.exceptions import BusinessError
    so = svc.get_sales_order(db, UUID(so_id))
    if not so:
        raise BusinessError("NOT_FOUND", "销售订单不存在", 404)
    return SalesOrderOut.model_validate(so)


@router.patch("/{so_id}", response_model=SalesOrderOut)
def update_so(so_id: str, payload: SalesOrderUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.core.exceptions import BusinessError
    so = svc.get_sales_order(db, UUID(so_id))
    if not so:
        raise BusinessError("NOT_FOUND", "销售订单不存在", 404)
    so = svc.update_sales_order(db, so, **payload.model_dump(exclude_none=True))
    db.commit()
    return SalesOrderOut.model_validate(so)
