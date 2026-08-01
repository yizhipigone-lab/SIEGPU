"""资金置换 API（只读查询）。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.funding import FundingReplacementOut
from app.services import funding_service as svc

router = APIRouter(prefix="/api/funding", tags=["资金置换"])


@router.get("/replacements", response_model=list[FundingReplacementOut])
def list_replacements(project_id: str | None = Query(None),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pid = uuid.UUID(project_id) if project_id else None
    return [FundingReplacementOut.model_validate(r) for r in svc.list_replacements(db, project_id=pid)]
