from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    project_id: UUID
    contract_id: UUID | None = None
    equipment_model_id: UUID
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    order_date: date | None = None
    expected_delivery_date: date | None = None


class DeliveryStageOut(BaseModel):
    id: UUID
    stage: str
    seq: int
    status: str
    planned_date: date | None
    actual_date: date | None
    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: UUID
    project_id: UUID
    equipment_model_id: UUID
    quantity: int
    unit_price: Decimal
    total_amount: Decimal
    status: str
    model_config = {"from_attributes": True}


class OrderDetail(OrderOut):
    contract_id: UUID | None
    stages: list[DeliveryStageOut]


class StageAdvance(BaseModel):
    status: Literal["进行中", "已完成"]
    actual_date: date | None = None


class LightOnRequest(BaseModel):
    actual_date: date
