from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import report_service as svc
from app.schemas.profit import ProfitScenarioCreate, ProfitScenarioOut
from app.services.profit_service import (
    ProfitInput, calculate_for_project, calculate_model,
    compare_scenarios, list_scenarios, save_scenario,
)

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


# —— v3.1 盈利测算场景 ——

@router.post("/profit/scenarios", response_model=ProfitScenarioOut, status_code=201)
def create_scenario(payload: ProfitScenarioCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from datetime import datetime as dt
    # 保存前先计算
    result = calculate_model(ProfitInput(**payload.params_json))
    sc = save_scenario(db, project_id=payload.project_id, name=payload.name,
                       params_json=payload.params_json, result_json=result,
                       is_actual=payload.is_actual, created_by=user.id)
    db.commit()
    return ProfitScenarioOut.model_validate(sc)


@router.get("/profit/scenarios/{project_id}", response_model=list[ProfitScenarioOut])
def list_project_scenarios(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import uuid
    return [ProfitScenarioOut.model_validate(s) for s in list_scenarios(db, project_id=uuid.UUID(project_id))]


@router.get("/profit/compare/{project_id}")
def compare_project_profit(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import uuid
    return compare_scenarios(db, project_id=uuid.UUID(project_id))


@router.get("/project-comparison")
def project_comparison(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.project_comparison(db)}


# —— v3.2 客户对账单（F3）——

@router.get("/customer-statement/summary")
def customer_statement_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.customer_statement_summary(db)}


@router.get("/customer-statement")
def customer_statement(customer_id: str, period: str | None = None,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """客户对账单（缺陷#18）：period='YYYY-MM' 当期口径，缺省=累计。"""
    import uuid
    return svc.customer_statement(db, uuid.UUID(customer_id), period=period)
