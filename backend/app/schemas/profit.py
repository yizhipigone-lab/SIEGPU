"""盈利测算 — Pydantic schemas。"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ProfitCalculateRequest(BaseModel):
    """前端手动测算请求。"""
    purchase_ex_tax: Decimal = Field(gt=0)
    purchase_incl_tax: Decimal = Field(gt=0)
    monthly_rent: Decimal = Field(gt=0)
    term_months: int = Field(gt=0)
    annual_rate: Decimal = Field(ge=0, lt=1)
    lease_term: int = Field(gt=0)
    payment_freq: str = "月"
    repayment_method: str = "等额本息"
    depreciation_years: int = 5
    residual_rate: Decimal = Decimal("0.10")
    monthly_opex: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0.06")
    equity_ratio: Decimal = Decimal("0.10")


class ProfitScenarioCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(max_length=200)
    params_json: dict
    is_actual: bool = False


class ProfitScenarioOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    params_json: dict
    result_json: dict
    is_actual: bool
    calculated_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
