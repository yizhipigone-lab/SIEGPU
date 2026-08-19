"""验收记录 — Pydantic schemas。"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class AcceptanceCreate(BaseModel):
    project_id: uuid.UUID
    acceptance_type: str = Field(description="采购验收 or 销售验收")
    order_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    inspector: str | None = None
    acceptance_date: date | None = None
    quantity_accepted: int = Field(default=0, ge=0)
    quantity_rejected: int = Field(default=0, ge=0)
    rejection_reason: str | None = None
    notes: str | None = None
    # W4：销售验收勾选「上架」→ 审批通过时同步标记订单/批次设备上架完成
    shelve: bool = False


class AcceptanceUpdate(BaseModel):
    inspector: str | None = None
    acceptance_date: date | None = None
    quantity_accepted: int | None = Field(default=None, ge=0)
    quantity_rejected: int | None = Field(default=None, ge=0)
    rejection_reason: str | None = None
    notes: str | None = None


class AcceptanceOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    acceptance_type: str
    order_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    status: str
    inspector: str | None = None
    acceptance_date: date | None = None
    quantity_accepted: int
    quantity_rejected: int
    rejection_reason: str | None = None
    file_path: str | None = None
    notes: str | None = None
    shelve: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
