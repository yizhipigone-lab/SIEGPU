from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    code: str | None = None
    customer_id: UUID | None = None
    total_investment: Decimal | None = None
    start_date: date | None = None
    business_type: str | None = None  # 经营租赁/转售/自营
    leasing_mode: str | None = None  # 自有/直租/售后回租
    parent_id: UUID | None = None
    financing_plan: dict | None = None
    template_id: UUID | None = None  # v3.2: 向导式工作流模板


class ProjectOut(BaseModel):
    id: UUID
    name: str
    code: str | None
    status: str
    total_investment: Decimal | None
    business_type: str | None = None
    leasing_mode: str | None = None
    parent_id: UUID | None = None
    financing_plan: dict | None = None

    model_config = {"from_attributes": True}
