from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.alert import AlertOut
from app.services import alert_service

router = APIRouter()


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = alert_service.compute_alerts(db)
    return {"items": [AlertOut(**r).model_dump() for r in rows], "total": len(rows)}
