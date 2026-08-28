from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class RepaymentConfirm(BaseModel):
    actual_principal: Decimal = Field(ge=0)
    actual_interest: Decimal = Field(ge=0)
    paid_date: date


class RepaymentPlanUpdate(BaseModel):
    """缺陷#11：还款计划调整（planned_* 均可选，只改传入项）。"""
    planned_principal: Decimal | None = Field(None, ge=0)
    planned_interest: Decimal | None = Field(None, ge=0)
    due_date: date | None = None


class RepaymentOut(BaseModel):
    id: UUID
    leasing_process_id: UUID
    period: int
    due_date: date
    planned_principal: Decimal
    planned_interest: Decimal
    actual_principal: Decimal | None
    actual_interest: Decimal | None
    paid_date: date | None
    status: str
    model_config = {"from_attributes": True}
