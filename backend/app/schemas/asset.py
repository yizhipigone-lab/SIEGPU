from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class AssetOut(BaseModel):
    id: UUID
    project_id: UUID
    equipment_model_id: UUID
    order_id: UUID | None
    quantity: int
    total_original_value: Decimal
    residual_value: Decimal
    depreciable_value: Decimal
    annual_depreciation: Decimal
    monthly_depreciation: Decimal
    start_date: date
    end_date: date
    status: str
    model_config = {"from_attributes": True}


class DepreciationRow(BaseModel):
    period: int
    month: date
    amount: Decimal
