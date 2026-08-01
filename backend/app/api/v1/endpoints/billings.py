from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.exceptions import BusinessError
from app.models.user import User
from app.schemas.billing import BillingGenerate, BillingOut
from app.services import billing_service as svc

router = APIRouter()


@router.get("")
def list_billings(contract_id: UUID | None = None, order_id: UUID | None = None,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_billings(db, contract_id=contract_id, order_id=order_id)
    return {"items": [BillingOut.model_validate(b).model_dump(mode="json") for b in rows], "total": len(rows)}


@router.post("", response_model=BillingOut, status_code=201)
def generate(payload: BillingGenerate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        b = svc.generate_billing(
            db, order_id=payload.order_id, contract_id=payload.contract_id,
            period_index=payload.period_index, billing_date=payload.billing_date,
            created_by=user.id, idempotency_key=payload.idempotency_key,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "该订单该期计费已存在", 409)
    return BillingOut.model_validate(b)
