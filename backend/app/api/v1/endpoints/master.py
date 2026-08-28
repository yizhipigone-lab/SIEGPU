"""主数据端点：suppliers / customers / equipment-models / banks。"""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.user import User
from app.schemas.master import (
    BankCreate,
    BankOut,
    CustomerCreate,
    CustomerOut,
    EquipmentModelCreate,
    EquipmentModelOut,
    SupplierCreate,
    SupplierOut,
)
from app.services import capital_service as cap_svc
from app.services import master_service as svc

suppliers_router = APIRouter()
customers_router = APIRouter()
equipment_models_router = APIRouter()
banks_router = APIRouter()


def _build(router: APIRouter, prefix_model, create_schema, out_schema, *, path_name: str, enrich=None):
    """为某个主数据实体生成标准 list/create/update/delete。enrich: (rows) -> dict 列表装饰。"""

    @router.get("")
    def _list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
        rows = svc.list_entities(db, prefix_model)
        if enrich is None:
            return {"items": [out_schema.model_validate(o).model_dump(mode="json") for o in rows], "total": len(rows)}
        return {"items": enrich(rows, db), "total": len(rows)}

    @router.post("", response_model=out_schema, status_code=201)
    def _create(payload: create_schema, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
        o = svc.create_entity(db, prefix_model, payload.model_dump())
        db.commit()
        return out_schema.model_validate(o)

    @router.patch("/{eid}", response_model=out_schema)
    def _update(eid: UUID, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
        o = svc.update_entity(db, prefix_model, eid, payload)
        db.commit()
        return out_schema.model_validate(o)

    @router.delete("/{eid}", status_code=204)
    def _delete(eid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
        svc.soft_delete_entity(db, prefix_model, eid)
        db.commit()


def _bank_enrich(rows, db):
    """缺陷#23：银行列表带授信使用情况（额度/已用/剩余，实时聚合）。"""
    used = cap_svc.bank_credit_usage(db)
    out = []
    for o in rows:
        item = BankOut.model_validate(o).model_dump(mode="json")
        u = used.get(str(o.id), Decimal(0))
        line = Decimal(o.credit_line) if o.credit_line is not None else None
        item["credit_used"] = float(u)
        item["credit_remaining"] = float(line - u) if line is not None else None
        out.append(item)
    return out


_build(suppliers_router, Supplier, SupplierCreate, SupplierOut, path_name="suppliers")
_build(customers_router, Customer, CustomerCreate, CustomerOut, path_name="customers")
_build(equipment_models_router, EquipmentModel, EquipmentModelCreate, EquipmentModelOut, path_name="equipment-models")
_build(banks_router, Bank, BankCreate, BankOut, path_name="banks", enrich=_bank_enrich)


@banks_router.get("/credit-usage")
def bank_credit_usage(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """缺陷#23：银行授信使用情况（额度/已用/剩余，按借款−偿还实时聚合）。"""
    used = cap_svc.bank_credit_usage(db)
    banks = svc.list_entities(db, Bank)
    items = []
    for b in banks:
        u = used.get(str(b.id), Decimal(0))
        line = Decimal(b.credit_line) if b.credit_line is not None else None
        items.append({
            "bank_id": str(b.id), "bank_name": b.name,
            "credit_line": float(line) if line is not None else None,
            "used": float(u),
            "remaining": float(line - u) if line is not None else None,
        })
    return {"items": items, "total": len(items)}
