"""资金池端点（一期核心）。对应设计书 §6.3 的 capital 段。"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.exceptions import BusinessError
from app.models.user import User
from app.schemas.capital import AllocationCreate, AllocationReturn, TransactionCreate, TransactionOut
from app.services import capital_service as svc

router = APIRouter()


@router.get("/transactions")
def list_transactions(
    direction: str | None = None,
    project_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = svc.list_transactions(db, project_id=project_id, direction=direction)
    return {"items": [TransactionOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.post("/transactions", response_model=TransactionOut, status_code=201)
def record_transaction(
    payload: TransactionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        txn = svc.record_transaction(db, created_by=user.id, **payload.model_dump())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复请求或约束冲突（幂等键/唯一约束）", 409)
    return TransactionOut.model_validate(txn)


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.pool_summary(db)


@router.get("/allocatable")
def allocatable(
    project_id: UUID = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"project_id": str(project_id), "allocatable": svc.project_allocatable(db, project_id)}


@router.post("/allocate", status_code=201)
def allocate(
    payload: AllocationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        alloc = svc.allocate(db, approved_by=user.id, **payload.model_dump())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复调配请求", 409)
    return {
        "allocation_id": str(alloc.id),
        "out_txn_id": str(alloc.out_txn_id),
        "in_txn_id": str(alloc.in_txn_id),
        "amount": alloc.amount,
    }


@router.post("/transactions/{txn_id}/reverse", status_code=201)
def reverse(
    txn_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        rev = svc.reverse_transaction(db, txn_id=txn_id, reversed_by=user.id, note="红冲")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "该流水已红冲", 409)
    return {"reversal_id": str(rev.id), "reversal_of": str(rev.reversal_of_id)}


@router.post("/allocations/{allocation_id}/return")
def return_allocation(allocation_id: UUID, payload: AllocationReturn,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    alloc = svc.return_allocation(db, allocation_id=allocation_id, returned_by=user.id,
                                  return_date=payload.return_date)
    db.commit()
    return {"allocation_id": str(alloc.id), "status": alloc.status,
            "actual_return_date": alloc.actual_return_date}
