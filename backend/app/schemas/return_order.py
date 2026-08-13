from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ReturnType = Literal["到货不合格", "压测不通过", "合同终止"]


class ReturnCreate(BaseModel):
    project_id: UUID
    return_type: ReturnType
    device_ids: list[UUID] = Field(min_length=1)
    original_order_id: UUID | None = None
    original_invoice_id: UUID | None = None
    reason: str | None = None


class ReturnOut(BaseModel):
    id: UUID
    project_id: UUID
    original_order_id: UUID | None
    original_invoice_id: UUID | None
    return_type: str
    status: str
    total_amount: Decimal
    prepayment_recover: Decimal
    reason: str | None
    red_invoice_id: UUID | None
    refund_txn_id: UUID | None
    created_at: datetime
    model_config = {"from_attributes": True}


class ReturnDeviceOut(BaseModel):
    id: UUID
    device_id: UUID
    amount: Decimal
    sn: str | None = None  # 端点填充
    model_config = {"from_attributes": True}


class ReturnAdvanceIn(BaseModel):
    transaction_date: date | None = None  # 红票/退款步骤的日期（缺省今天）
