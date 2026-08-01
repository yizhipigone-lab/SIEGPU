from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.repayment import RepaymentConfirm, RepaymentOut
from app.services import repayment_service as svc

router = APIRouter()


@router.get("")
def list_repayments(leasing_process_id: UUID, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    rows = svc.list_repayments(db, leasing_process_id)
    return {"items": [RepaymentOut.model_validate(r).model_dump(mode="json") for r in rows], "total": len(rows)}


@router.patch("/{repayment_id}", response_model=RepaymentOut)
def confirm(repayment_id: UUID, payload: RepaymentConfirm, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    r = svc.confirm_repayment(
        db, repayment_id=repayment_id, actual_principal=payload.actual_principal,
        actual_interest=payload.actual_interest, paid_date=payload.paid_date,
    )
    db.commit()
    return RepaymentOut.model_validate(r)
