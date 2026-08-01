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


class ProjectOut(BaseModel):
    id: UUID
    name: str
    code: str | None
    status: str
    total_investment: Decimal | None

    model_config = {"from_attributes": True}
