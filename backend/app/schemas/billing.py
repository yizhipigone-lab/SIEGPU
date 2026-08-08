from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BillingGenerate(BaseModel):
    order_id: UUID
    contract_id: UUID
    period_index: int = Field(gt=0)
    billing_date: date
    idempotency_key: str | None = None


class BillingGenerateDevice(BaseModel):
    """一期 W5-6 按台计费：金额取 device.monthly_price（不读 contract.monthly_rent）。"""
    device_id: UUID
    contract_id: UUID
    period_index: int = Field(gt=0)
    billing_date: date
    idempotency_key: str | None = None


class BillingOut(BaseModel):
    id: UUID
    contract_id: UUID
    order_id: UUID | None = None  # W5-6：按台计费 billings 可无订单
    device_id: UUID | None = None
    sales_order_id: UUID | None = None
    period_index: int
    period_label: str
    billing_date: date
    days_in_period: int
    amount: Decimal
    amount_ex_tax: Decimal
    tax_amount: Decimal
    status: str
    model_config = {"from_attributes": True}
