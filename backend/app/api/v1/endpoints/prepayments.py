"""预付款台账 + 单据编号规则 + 金租规则参数端点（二期 W9-10）。main.py 挂 prefix=/api。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import contract_amendment_service as amend_svc
from app.services import doc_number_service, prepayment_service

router = APIRouter()


@router.get("/prepayments/summary")
def prepayment_summary(project_id: UUID | None = None,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """预付款台账（D2：聚合 devices 行，单一真源）：总额/已结转/余额/结清标记。"""
    rows = prepayment_service.prepayment_summary(db, project_id=project_id)
    # Decimal → float（JSON 序列化）
    for r in rows:
        for k in ("prepayment_amount", "settled_amount", "remaining"):
            r[k] = float(r[k])
    return {"items": rows, "total": len(rows)}


@router.get("/doc-number-rules")
def list_doc_number_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = doc_number_service.list_rules(db)
    return {"items": [{
        "id": str(r.id), "doc_type": r.doc_type, "prefix": r.prefix,
        "date_format": r.date_format, "seq_digits": r.seq_digits,
        "current_period": r.current_period, "last_seq": r.last_seq, "active": r.active,
    } for r in rows], "total": len(rows)}


@router.get("/leasing-rule-configs")
def list_leasing_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = amend_svc.list_leasing_rules(db)
    return {"items": [{
        "id": str(r.id), "rule_key": r.rule_key, "rule_value": r.rule_value,
        "description": r.description,
    } for r in rows], "total": len(rows)}


@router.post("/leasing-rule-configs", status_code=201)
def set_leasing_rule(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """upsert 金租规则参数（同 key 覆盖）。"""
    r = amend_svc.set_leasing_rule(db, rule_key=payload["rule_key"],
                                   rule_value=payload["rule_value"],
                                   description=payload.get("description"))
    db.commit()
    return {"id": str(r.id), "rule_key": r.rule_key, "rule_value": r.rule_value,
            "description": r.description}
