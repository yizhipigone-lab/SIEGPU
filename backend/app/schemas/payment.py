from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PaymentRequestIn(BaseModel):
    project_id: UUID
    contract_id: UUID | None = None
    direction: Literal["IN", "OUT"] = "OUT"
    amount: Decimal = Field(gt=0)
    currency_code: str | None = None
    reason: str | None = None
    prepayment_offset: Decimal = Field(default=Decimal("0"), ge=0)


class PaymentRequestOut(BaseModel):
    id: UUID
    project_id: UUID
    contract_id: UUID | None
    direction: str
    amount: Decimal
    currency_code: str | None
    reason: str | None
    prepayment_offset: Decimal
    status: str
    approval_id: UUID | None
    capital_transaction_id: UUID | None
    created_at: datetime
    model_config = {"from_attributes": True}


class PoolSplit(BaseModel):
    """四期 W4：付款按资金池拆分的一笔（pool + amount）。"""
    pool: Literal["OWN", "LEASING", "BANK"]
    amount: Decimal = Field(gt=0)


class DisburseIn(BaseModel):
    transaction_date: date
    settlement_rate: Decimal | None = Field(None, gt=0)
    bank_id: UUID | None = None
    # 四期 W4：按资金池拆分支付（可选）。给则按各池金额生成多笔流水，Σ须等于实付现金；不给则单流入自有池。
    pool_splits: list[PoolSplit] | None = None


class ApprovalOut(BaseModel):
    id: UUID
    biz_type: str
    biz_id: UUID | None
    title: str
    status: str
    level: int
    submitted_by: UUID | None
    approved_by: UUID | None
    approved_at: datetime | None
    reject_reason: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class RejectIn(BaseModel):
    reason: str = Field(min_length=1)


class SettlementAlloc(BaseModel):
    amount: Decimal = Field(gt=0)
    invoice_id: UUID | None = None
    batch_id: UUID | None = None
    device_id: UUID | None = None


class SettleIn(BaseModel):
    txn_id: UUID
    allocations: list[SettlementAlloc] = Field(min_length=1)


class SettlementOut(BaseModel):
    id: UUID
    capital_transaction_id: UUID
    invoice_id: UUID | None
    batch_id: UUID | None
    device_id: UUID | None
    amount: Decimal
    created_at: datetime
    model_config = {"from_attributes": True}
