from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import report_service as svc
from app.services.profit_service import ProfitInput, calculate_for_project, calculate_model

router = APIRouter()


@router.get("/capital-monthly")
def capital_monthly(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.capital_monthly(db)}


@router.get("/project-overview")
def project_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.project_overview(db)}


@router.get("/receivables-aging")
def receivables_aging(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.receivables_aging(db)


@router.post("/profit/calculate")
def calc_profit(payload: ProfitInput, user: User = Depends(get_current_user)):
    return calculate_model(payload)


@router.get("/profit/{project_id}")
def project_profit(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return calculate_for_project(db, project_id)
