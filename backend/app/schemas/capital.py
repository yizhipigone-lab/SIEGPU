from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SourceType = Literal["自有资金", "银行流贷", "金租融资", "租金收入", "调配", "调配归还", "还款"]
Direction = Literal["IN", "OUT"]


class TransactionCreate(BaseModel):
    project_id: UUID
    source_type: SourceType
    direction: Direction
    amount: Decimal = Field(gt=0)
    transaction_date: date
    category: str | None = None
    note: str | None = None
    bank_id: UUID | None = None
    contract_id: UUID | None = None
    leasing_process_id: UUID | None = None
    idempotency_key: str | None = None
    # 二期 W5-6：外币收付（amount=交易币种金额；base_amount=人民币，仅外币有值）
    currency_code: str | None = None
    settlement_rate: Decimal | None = Field(None, gt=0)
    base_amount: Decimal | None = Field(None, ge=0)


class TransactionOut(BaseModel):
    id: UUID
    project_id: UUID | None
    source_type: str
    direction: str
    amount: Decimal
    transaction_date: date
    category: str | None
    note: str | None
    idempotency_key: str | None
    is_reversal: bool
    currency_code: str | None = None
    settlement_rate: Decimal | None = None
    base_amount: Decimal | None = None

    model_config = {"from_attributes": True}


class AllocationCreate(BaseModel):
    from_project_id: UUID
    to_project_id: UUID
    amount: Decimal = Field(gt=0)
    allocation_date: date
    expected_return_date: date | None = None
    reason: str | None = None


class AllocationReturn(BaseModel):
    return_date: date
