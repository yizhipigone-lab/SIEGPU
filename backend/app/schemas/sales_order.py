"""销售订单 — Pydantic schemas。"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SalesOrderCreate(BaseModel):
    project_id: uuid.UUID
    contract_id: uuid.UUID
    equipment_model_id: uuid.UUID
    quantity: int = Field(gt=0)
    monthly_rent_per_unit: Decimal = Field(gt=0)
    total_monthly_rent: Decimal = Field(gt=0)
    start_date: date | None = None
    end_date: date | None = None
    status: str = "待交付"
    notes: str | None = None
    # W4：销售批次（照采购批次订单）
    is_batch: bool = False
    batch_name: str | None = None


class SalesOrderUpdate(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    monthly_rent_per_unit: Decimal | None = Field(default=None, gt=0)
    total_monthly_rent: Decimal | None = Field(default=None, gt=0)
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    notes: str | None = None


class SalesOrderOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    contract_id: uuid.UUID
    equipment_model_id: uuid.UUID
    quantity: int
    monthly_rent_per_unit: Decimal
    total_monthly_rent: Decimal
    start_date: date | None = None
    end_date: date | None = None
    status: str
    notes: str | None = None
    is_batch: bool = False
    batch_name: str | None = None
    batch_status: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---- W4：销售批次-设备组合 ----

class SalesBatchAssign(BaseModel):
    device_id: uuid.UUID
    sales_batch_id: uuid.UUID


class SalesBatchRemove(BaseModel):
    device_id: uuid.UUID


class SalesBatchDeviceOut(BaseModel):
    id: uuid.UUID
    sales_batch_id: uuid.UUID
    device_id: uuid.UUID
    action: str
    active: bool
    operated_by: uuid.UUID | None
    model_config = {"from_attributes": True}
