from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class AssetOut(BaseModel):
    id: UUID
    project_id: UUID
    equipment_model_id: UUID
    order_id: UUID | None
    device_id: UUID | None
    quantity: int
    unit_original_value: Decimal
    total_original_value: Decimal
    residual_value: Decimal | None
    depreciable_value: Decimal | None
    annual_depreciation: Decimal | None
    monthly_depreciation: Decimal | None
    start_date: date | None
    end_date: date | None
    status: str
    operation_status: str
    model_config = {"from_attributes": True}


class DepreciationRow(BaseModel):
    period: int
    month: date
    amount: Decimal
