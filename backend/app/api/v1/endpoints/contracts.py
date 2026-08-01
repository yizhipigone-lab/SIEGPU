from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.contract import ContractCreate, ContractOut
from app.services import contract_service as svc

router = APIRouter()


@router.get("")
def list_contracts(project_id: UUID | None = None, type: str | None = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_contracts(db, project_id=project_id, type=type)
    return {"items": [ContractOut.model_validate(c).model_dump(mode="json") for c in rows], "total": len(rows)}


@router.post("", response_model=ContractOut, status_code=201)
def create_contract(payload: ContractCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.create_contract(db, **payload.model_dump())
    db.commit()
    return ContractOut.model_validate(c)


@router.get("/{cid}", response_model=ContractOut)
def get_contract(cid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ContractOut.model_validate(svc.get_contract_or_404(db, cid))


@router.delete("/{cid}", status_code=204)
def delete_contract(cid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.get_contract_or_404(db, cid)
    from datetime import datetime, timezone
    c.deleted_at = datetime.now(timezone.utc)
    db.commit()
