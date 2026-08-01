"""销售订单 API。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.sales_order import SalesOrderCreate, SalesOrderOut, SalesOrderUpdate
from app.services import sales_order_service as svc

router = APIRouter(prefix="/api/sales-orders", tags=["销售订单"])


@router.post("", response_model=SalesOrderOut, status_code=201)
def create_so(payload: SalesOrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    so = svc.create_sales_order(db, **payload.model_dump())
    db.commit()
    return SalesOrderOut.model_validate(so)


@router.get("", response_model=list[SalesOrderOut])
def list_sos(project_id: str | None = Query(None), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import uuid
    pid = uuid.UUID(project_id) if project_id else None
    return [SalesOrderOut.model_validate(s) for s in svc.list_sales_orders(db, project_id=pid)]


@router.get("/{so_id}", response_model=SalesOrderOut)
def get_so(so_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import uuid
    so = svc.get_sales_order(db, uuid.UUID(so_id))
    if not so:
        from app.core.exceptions import BusinessError
        raise BusinessError("NOT_FOUND", "销售订单不存在", 404)
    return SalesOrderOut.model_validate(so)


@router.patch("/{so_id}", response_model=SalesOrderOut)
def update_so(so_id: str, payload: SalesOrderUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import uuid
    so = svc.get_sales_order(db, uuid.UUID(so_id))
    if not so:
        from app.core.exceptions import BusinessError
        raise BusinessError("NOT_FOUND", "销售订单不存在", 404)
    so = svc.update_sales_order(db, so, **payload.model_dump(exclude_none=True))
    db.commit()
    return SalesOrderOut.model_validate(so)
