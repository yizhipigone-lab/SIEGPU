"""付款管控 + 通用审批端点（二期 W11-12）。main.py 挂 prefix=/api。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.payment import (ApprovalOut, DisburseIn, PaymentRequestIn, PaymentRequestOut,
                                 RejectIn, SettleIn, SettlementOut)
from app.services import approval_service, payment_service as svc

router = APIRouter()


# ------------------------------ 付款申请 ------------------------------

@router.get("/payment-requests")
def list_requests(project_id: UUID | None = None, status: str | None = None,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_requests(db, project_id=project_id, status=status)
    return {"items": [PaymentRequestOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}


@router.post("/payment-requests", response_model=PaymentRequestOut, status_code=201)
def create_request(payload: PaymentRequestIn,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pr = svc.create_request(db, requested_by=user.id, **payload.model_dump())
    db.commit()
    return PaymentRequestOut.model_validate(pr)


@router.post("/payment-requests/{rid}/disburse", status_code=201)
def disburse(rid: UUID, payload: DisburseIn,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """登记付款（已批准 → 落资金流水；预付款冲抵视同结转）。"""
    txn = svc.disburse(db, rid, transaction_date=payload.transaction_date,
                       settlement_rate=payload.settlement_rate, bank_id=payload.bank_id,
                       actor_id=user.id)
    db.commit()
    return {"txn_id": str(txn.id), "amount": str(txn.amount)}


# ------------------------------ 审批中心 ------------------------------

@router.get("/approvals")
def list_approvals(biz_type: str | None = None, status: str | None = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = approval_service.list_approvals(db, biz_type=biz_type, status=status)
    return {"items": [ApprovalOut.model_validate(a).model_dump(mode="json") for a in rows],
            "total": len(rows)}


@router.post("/approvals/{aid}/approve", response_model=ApprovalOut)
def approve(aid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = approval_service.approve(db, aid, approved_by=user.id)
    db.commit()
    return ApprovalOut.model_validate(a)


@router.post("/approvals/{aid}/reject", response_model=ApprovalOut)
def reject(aid: UUID, payload: RejectIn,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = approval_service.reject(db, aid, reason=payload.reason, approved_by=user.id)
    db.commit()
    return ApprovalOut.model_validate(a)


# ------------------------------ 核销 ------------------------------

@router.post("/payment-settlements", status_code=201)
def settle(payload: SettleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """多对多核销：一笔流水拆到多发票/多批次/多台设备；外币自动汇兑损益分摊至设备。"""
    rows = svc.settle(db, txn_id=payload.txn_id,
                      allocations=[a.model_dump() for a in payload.allocations],
                      actor_id=user.id)
    db.commit()
    return {"items": [SettlementOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.get("/payment-settlements")
def list_settlements(txn_id: UUID | None = None, invoice_id: UUID | None = None,
                     device_id: UUID | None = None,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_settlements(db, txn_id=txn_id, invoice_id=invoice_id, device_id=device_id)
    return {"items": [SettlementOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}
