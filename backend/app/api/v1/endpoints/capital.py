"""资金池端点（一期核心）。对应设计书 §6.3 的 capital 段。"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.exceptions import BusinessError
from app.models.user import User
from app.schemas.capital import (AllocationCreate, AllocationReturn, BankLoanCreate, BankRepayCreate,
                                 PrepaymentCreate, PrepaymentOffset, PrepaymentRefund,
                                 TransactionCreate, TransactionOut)
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


@router.get("/pools")
def pools(project_id: UUID = Query(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """四期 W4：某项目 4 资金池余额（金租/银行/预付挂账/自有）。"""
    return {"project_id": str(project_id), "pools": svc.pools_by_project(db, project_id),
            "labels": svc.POOL_LABELS}


# ---------------- 四期 W4：资金池专用动作 ----------------

@router.post("/bank-loan", response_model=TransactionOut, status_code=201)
def bank_loan(payload: BankLoanCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """记一笔银行借款 → 银行池 IN。"""
    try:
        txn = svc.record_bank_loan(db, created_by=user.id, **payload.model_dump())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复请求（幂等键冲突）", 409)
    return TransactionOut.model_validate(txn)


@router.post("/repay-bank", response_model=TransactionOut, status_code=201)
def repay_bank(payload: BankRepayCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """还银行 → 银行池 OUT（余额不足 400）。"""
    try:
        txn = svc.repay_bank(db, created_by=user.id, **payload.model_dump())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复请求（幂等键冲突）", 409)
    return TransactionOut.model_validate(txn)


@router.post("/prepayment", status_code=201)
def prepayment(payload: PrepaymentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """预付：现金池(from_pool) OUT + 预付款池(挂账) IN。"""
    try:
        cash_out, hang_in = svc.record_prepayment(db, created_by=user.id, **payload.model_dump())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复请求（幂等键冲突）", 409)
    return {"cash_txn_id": str(cash_out.id), "hang_txn_id": str(hang_in.id), "amount": str(hang_in.amount)}


@router.post("/prepayment/refund", status_code=201)
def prepayment_refund(payload: PrepaymentRefund, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """预付退回：预付款池 OUT + 现金回到 to_pool IN。"""
    try:
        hang_out, cash_in = svc.refund_prepayment(db, created_by=user.id, **payload.model_dump())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复请求（幂等键冲突）", 409)
    return {"hang_txn_id": str(hang_out.id), "cash_txn_id": str(cash_in.id), "amount": str(cash_in.amount)}


@router.post("/prepayment/offset", response_model=TransactionOut, status_code=201)
def prepayment_offset(payload: PrepaymentOffset, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """预付核销：预付款池 OUT，抵减应付（不涉现金）。"""
    try:
        txn = svc.offset_prepayment(db, created_by=user.id, **payload.model_dump())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复请求（幂等键冲突）", 409)
    return TransactionOut.model_validate(txn)


@router.get("/pool-by-project")
def pool_by_project(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.pool_by_project(db)}


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


@router.get("/allocations")
def list_allocations(project_id: UUID | None = Query(None),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_allocations(db, project_id=project_id)
    return {"items": [{ "id": str(a.id), "from_project_id": str(a.from_project_id),
        "to_project_id": str(a.to_project_id), "amount": a.amount,
        "allocation_date": a.allocation_date.isoformat() if a.allocation_date else None,
        "status": a.status, "reason": a.reason, "expected_return_date":
        a.expected_return_date.isoformat() if a.expected_return_date else None,
    } for a in rows]}


@router.post("/allocations/{allocation_id}/return")
def return_allocation(allocation_id: UUID, payload: AllocationReturn,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    alloc = svc.return_allocation(db, allocation_id=allocation_id, returned_by=user.id,
                                  return_date=payload.return_date)
    db.commit()
    return {"allocation_id": str(alloc.id), "status": alloc.status,
            "actual_return_date": alloc.actual_return_date}
