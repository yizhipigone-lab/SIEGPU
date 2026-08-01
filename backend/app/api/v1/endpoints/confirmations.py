"""客户确认单 API。"""
import uuid

from fastapi import APIRouter, Depends, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.exceptions import BusinessError
from app.models.user import User
from app.schemas.confirmation import ConfirmationCreate, ConfirmationOut, ConfirmationUpdate
from app.services import confirmation_service as svc

router = APIRouter(prefix="/api/confirmations", tags=["客户确认单"])


@router.post("", response_model=ConfirmationOut, status_code=201)
def create_conf(payload: ConfirmationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sc = svc.create_confirmation(
        db, billing_id=payload.billing_id, sales_order_id=payload.sales_order_id,
        period_label=payload.period_label, created_by=user.id,
    )
    db.commit()
    return ConfirmationOut.model_validate(sc)


@router.get("", response_model=list[ConfirmationOut])
def list_confs(sales_order_id: str | None = Query(None),
               status: str | None = Query(None),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = uuid.UUID(sales_order_id) if sales_order_id else None
    return [ConfirmationOut.model_validate(c) for c in svc.list_confirmations(db, sales_order_id=sid, status=status)]


@router.post("/{sc_id}/confirm", response_model=ConfirmationOut)
def confirm_sc(sc_id: str, confirmed_by_customer: str = Query(...),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sc = svc.get_confirmation(db, uuid.UUID(sc_id))
    if not sc:
        raise BusinessError("NOT_FOUND", "确认单不存在", 404)
    sc = svc.confirm(db, sc, confirmed_by_customer=confirmed_by_customer, operator_id=user.id)
    db.commit()
    return ConfirmationOut.model_validate(sc)


@router.post("/{sc_id}/dispute", response_model=ConfirmationOut)
def dispute_sc(sc_id: str, reason: str = Query(...),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sc = svc.get_confirmation(db, uuid.UUID(sc_id))
    if not sc:
        raise BusinessError("NOT_FOUND", "确认单不存在", 404)
    sc = svc.dispute(db, sc, reason)
    db.commit()
    return ConfirmationOut.model_validate(sc)
