from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.asset import AssetOut, DepreciationRow
from app.services import asset_service as svc

router = APIRouter()


@router.get("")
def list_assets(project_id: UUID | None = None, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    rows = svc.list_assets(db, project_id=project_id)
    return {"items": [AssetOut.model_validate(a).model_dump(mode="json") for a in rows], "total": len(rows)}


@router.get("/{aid}", response_model=AssetOut)
def get_asset(aid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return AssetOut.model_validate(svc.get_asset_or_404(db, aid))


@router.get("/{aid}/depreciation-schedule")
def depreciation_schedule(aid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.depreciation_schedule(db, aid)
    return {"items": [DepreciationRow(**r).model_dump(mode="json") for r in rows],
            "total": len(rows), "sum": sum((r["amount"] for r in rows), Decimal(0)) if rows else 0}
