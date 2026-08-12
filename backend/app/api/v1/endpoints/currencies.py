"""币种与汇率端点（二期 W5-6）。

路由（main.py 挂 prefix=/api）：
- GET/POST /currencies，PATCH /currencies/{id}（设本币自动让其他退位）
- GET/POST /exchange-rates，GET /exchange-rates/lookup?from&to&date（取值=最近不未来；须在 /exchange-rates/{...} 之前无冲突——无 id 路由）
- GET/POST /exchange-gain-loss-rules（场景唯一）
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.currency import (CurrencyIn, CurrencyOut, CurrencyPatch, GlRuleIn, GlRuleOut,
                                  RateIn, RateLookupOut, RateOut)
from app.services import exchange_service as svc

router = APIRouter()


# ------------------------------ 币种 ------------------------------

@router.get("/currencies")
def list_currencies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_currencies(db)
    return {"items": [CurrencyOut.model_validate(c).model_dump(mode="json") for c in rows], "total": len(rows)}


@router.post("/currencies", response_model=CurrencyOut, status_code=201)
def create_currency(payload: CurrencyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.create_currency(db, **payload.model_dump())
    db.commit()
    return CurrencyOut.model_validate(c)


@router.patch("/currencies/{cid}", response_model=CurrencyOut)
def update_currency(cid: UUID, payload: CurrencyPatch,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.core.exceptions import BusinessError
    c = svc.update_currency(db, cid, payload.model_dump(exclude_unset=True))
    if c is None:
        raise BusinessError("NOT_FOUND", "币种不存在", 404)
    db.commit()
    return CurrencyOut.model_validate(c)


# ------------------------------ 汇率 ------------------------------

@router.get("/exchange-rates/lookup", response_model=RateLookupOut)
def lookup_rate(from_currency: str, to_currency: str, on_date: date, rate_type: str = "中间价",
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """汇率试算/取值（最近不未来）；无记录 404（不静默按 1 折算）。"""
    r = svc.get_rate(db, from_currency, to_currency, on_date, rate_type)
    return RateLookupOut(from_currency=from_currency.upper(), to_currency=to_currency.upper(),
                         rate_type=rate_type, on_date=on_date, rate=r)


@router.get("/exchange-rates")
def list_rates(from_currency: str | None = None, to_currency: str | None = None,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_rates(db, from_currency, to_currency)
    return {"items": [RateOut.model_validate(r).model_dump(mode="json") for r in rows], "total": len(rows)}


@router.post("/exchange-rates", response_model=RateOut, status_code=201)
def add_rate(payload: RateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = svc.add_rate(db, **payload.model_dump())
    db.commit()
    return RateOut.model_validate(r)


# ------------------------------ 汇兑损益科目规则 ------------------------------

@router.get("/exchange-gain-loss-rules")
def list_gl_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_gl_rules(db)
    return {"items": [GlRuleOut.model_validate(r).model_dump(mode="json") for r in rows], "total": len(rows)}


@router.post("/exchange-gain-loss-rules", response_model=GlRuleOut, status_code=201)
def create_gl_rule(payload: GlRuleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = svc.create_gl_rule(db, **payload.model_dump())
    db.commit()
    return GlRuleOut.model_validate(r)
