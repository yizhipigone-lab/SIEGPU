"""金租流程端点（一期核心）。对应设计书 §6.3 的 leasing 段。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.exceptions import BusinessError
from app.models.user import User
from app.schemas.leasing import (
    DisbursementCreate,
    DisbursementOut,
    DisburseRequest,
    LeasingNodeOut,
    LeasingProcessCreate,
    LeasingProcessDetail,
    LeasingProcessOut,
    NodeAdvance,
)
from app.services import leasing_service as svc

router = APIRouter()


def _detail(proc, nodes, project=None, supplier=None) -> LeasingProcessDetail:
    return LeasingProcessDetail(
        id=proc.id, project_id=proc.project_id, project_name=project.name if project else None,
        supplier_id=proc.supplier_id, supplier_name=supplier.name if supplier else None,
        total_amount=proc.total_amount, status=proc.status,
        disbursement_date=proc.disbursement_date, plan_generated=proc.plan_generated,
        leasing_mode=proc.leasing_mode, financing_type=proc.financing_type,
        materials=proc.materials,
        nodes=[LeasingNodeOut.model_validate(n) for n in nodes],
    )


@router.get("/processes")
def list_processes(project_id: UUID | None = None, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    rows = svc.list_processes(db, project_id=project_id)
    return {
        "items": [LeasingProcessOut.model_validate(p).model_dump(mode="json") for p in rows],
        "total": len(rows),
    }


@router.post("/processes", response_model=LeasingProcessDetail, status_code=201)
def create_process(payload: LeasingProcessCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    proc = svc.create_process(db, **payload.model_dump())
    db.commit()
    proc, nodes, proj, sup = svc.get_process(db, proc.id)
    return _detail(proc, nodes, proj, sup)


@router.get("/processes/{process_id}", response_model=LeasingProcessDetail)
def get_process(process_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    proc, nodes, proj, sup = svc.get_process(db, process_id)
    return _detail(proc, nodes, proj, sup)


@router.patch("/processes/{process_id}", response_model=LeasingProcessOut)
def update_process(process_id: UUID, payload: dict, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """缺陷#10：编辑金租申请（仅进行中未放款：金额/利率/期数/频率/方式等）。"""
    proc = svc.update_process(db, process_id=process_id, operator_id=user.id, **payload)
    db.commit()
    return LeasingProcessOut.model_validate(proc)


@router.post("/processes/{process_id}/void", response_model=LeasingProcessOut)
def void_process(process_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """缺陷#10：作废金租申请（仅未放款）。"""
    proc = svc.void_process(db, process_id=process_id, operator_id=user.id)
    db.commit()
    return LeasingProcessOut.model_validate(proc)


@router.patch("/nodes/{node_id}")
def advance_node(node_id: UUID, payload: NodeAdvance, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    node = svc.advance_node(db, node_id=node_id, status=payload.status,
                            actual_date=payload.actual_date, stuck_reason=payload.stuck_reason)
    db.commit()
    return {"id": str(node.id), "status": node.status}


@router.post("/processes/{process_id}/disburse")
def disburse(process_id: UUID, payload: DisburseRequest, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    try:
        proc, txn, n = svc.disburse(
            db, process_id=process_id,
            actual_disbursement_amount=payload.actual_disbursement_amount,
            disbursement_date=payload.disbursement_date, disbursed_by=user.id, note=payload.note,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复放款", 409)
    return {
        "process_id": str(proc.id),
        "capital_transaction_id": str(txn.id),
        "repayments_generated": n,
    }


@router.get("/processes/{process_id}/disbursements")
def list_disbursements(process_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_disbursements(db, process_id)
    return {"items": [DisbursementOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.post("/processes/{process_id}/disbursements", response_model=DisbursementOut, status_code=201)
def add_disbursement(process_id: UUID, payload: DisbursementCreate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    try:
        d, _, _ = svc.add_disbursement(db, process_id=process_id, acceptance_id=payload.acceptance_id,
                                       amount=payload.amount, disbursement_date=payload.disbursement_date,
                                       mode=payload.mode, replacement_date=payload.replacement_date,
                                       note=payload.note, created_by=user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessError("DUPLICATE", "重复放款", 409)
    return DisbursementOut.model_validate(d)
