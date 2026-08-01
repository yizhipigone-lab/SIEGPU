"""主数据端点：suppliers / customers / equipment-models / banks。"""
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
from app.services import master_service as svc

suppliers_router = APIRouter()
customers_router = APIRouter()
equipment_models_router = APIRouter()
banks_router = APIRouter()


def _build(router: APIRouter, prefix_model, create_schema, out_schema, *, path_name: str):
    """为某个主数据实体生成标准 list/create/update/delete。"""

    @router.get("")
    def _list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
        rows = svc.list_entities(db, prefix_model)
        return {"items": [out_schema.model_validate(o).model_dump(mode="json") for o in rows], "total": len(rows)}

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


_build(suppliers_router, Supplier, SupplierCreate, SupplierOut, path_name="suppliers")
_build(customers_router, Customer, CustomerCreate, CustomerOut, path_name="customers")
_build(equipment_models_router, EquipmentModel, EquipmentModelCreate, EquipmentModelOut, path_name="equipment-models")
_build(banks_router, Bank, BankCreate, BankOut, path_name="banks")
