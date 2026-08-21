from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class RecognitionOut(BaseModel):
    id: UUID
    project_id: UUID
    contract_id: UUID
    batch_id: UUID | None
    device_id: UUID | None
    billing_id: UUID | None
    invoice_id: UUID | None = None  # 四期 W4 期2：收入按开票确认，关联来源发票
    period_label: str
    recognition_date: date
    amount: Decimal
    currency_code: str | None
    booked_rate: Decimal | None
    revenue_method: str | None
    status: str
    approval_id: UUID | None
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    voucher_json: dict | None
    created_at: datetime
    model_config = {"from_attributes": True}


class MappingIn(BaseModel):
    business_event: str = Field(min_length=1, max_length=50)
    revenue_method: str | None = None  # NULL=通用
    debit_account: str = Field(min_length=1, max_length=50)
    credit_account: str = Field(min_length=1, max_length=50)
    description_template: str | None = None


class MappingOut(BaseModel):
    id: UUID
    business_event: str
    revenue_method: str | None
    debit_account: str
    credit_account: str
    description_template: str | None
    model_config = {"from_attributes": True}
