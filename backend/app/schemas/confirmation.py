"""客户确认单 — Pydantic schemas。"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class ConfirmationCreate(BaseModel):
    billing_id: uuid.UUID
    sales_order_id: uuid.UUID
    period_label: str
    confirmed_by_customer: str | None = None
    confirmed_at: date | None = None
    status: str = "待确认"


class ConfirmationUpdate(BaseModel):
    confirmed_by_customer: str | None = None
    confirmed_at: date | None = None
    status: str | None = None
    dispute_reason: str | None = None


class ConfirmationOut(BaseModel):
    id: uuid.UUID
    billing_id: uuid.UUID
    sales_order_id: uuid.UUID
    period_label: str
    file_path: str | None = None
    confirmed_by_customer: str | None = None
    confirmed_at: date | None = None
    status: str
    dispute_reason: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
