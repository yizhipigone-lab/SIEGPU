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


@router.get("/business")
def business(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """三期 §4.5 经营看板：核心指标 + 待办中心 + 资金预测概览（简易版）+ EBS 同步状态。"""
    from app.services import business_board_service
    return business_board_service.business_board(db)
