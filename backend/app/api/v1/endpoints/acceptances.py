"""验收记录 API。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.exceptions import BusinessError
from app.models.user import User
from app.schemas.acceptance import AcceptanceCreate, AcceptanceOut
from app.services import acceptance_service as svc

router = APIRouter(prefix="/api/acceptances", tags=["验收记录"])


@router.post("", response_model=AcceptanceOut, status_code=201)
def create_ar(payload: AcceptanceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ar = svc.create_acceptance(db, **payload.model_dump(exclude={'acceptance_date', 'rejection_reason'}))
    db.commit()
    return AcceptanceOut.model_validate(ar)


@router.get("", response_model=list[AcceptanceOut])
def list_ars(project_id: str | None = Query(None),
             acceptance_type: str | None = Query(None),
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pid = uuid.UUID(project_id) if project_id else None
    return [AcceptanceOut.model_validate(a) for a in svc.list_acceptances(db, project_id=pid, acceptance_type=acceptance_type)]


@router.get("/{ar_id}", response_model=AcceptanceOut)
def get_ar(ar_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ar = svc.get_acceptance(db, uuid.UUID(ar_id))
    if not ar:
        raise BusinessError("NOT_FOUND", "验收记录不存在", 404)
    return AcceptanceOut.model_validate(ar)


@router.post("/{ar_id}/approve", response_model=AcceptanceOut)
def approve_ar(ar_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ar = svc.get_acceptance(db, uuid.UUID(ar_id))
    if not ar:
        raise BusinessError("NOT_FOUND", "验收记录不存在", 404)
    ar = svc.approve_acceptance(db, ar, approved_by=user.id)
    db.commit()
    return AcceptanceOut.model_validate(ar)


@router.post("/{ar_id}/reject", response_model=AcceptanceOut)
def reject_ar(ar_id: str, reason: str = Query(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ar = svc.get_acceptance(db, uuid.UUID(ar_id))
    if not ar:
        raise BusinessError("NOT_FOUND", "验收记录不存在", 404)
    ar = svc.reject_acceptance(db, ar, reason, rejected_by=user.id)
    db.commit()
    return AcceptanceOut.model_validate(ar)
