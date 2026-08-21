from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SourceType = Literal["自有资金", "银行流贷", "金租融资", "租金收入", "调配", "调配归还", "还款",
                     "归还流贷", "归还自有", "汇兑损益", "预付", "归还银行"]
Direction = Literal["IN", "OUT"]
# 四期 W4：资金池（OWN 自有 / LEASING 金租 / BANK 银行 / PREPAY 预付款挂账）
Pool = Literal["OWN", "LEASING", "BANK", "PREPAY"]


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
    # 四期 W4：资金池归属（缺省 OWN）
    pool: Pool = "OWN"


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
    pool: str = "OWN"

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


# ---------------- 四期 W4：资金池专用动作 ----------------

class BankLoanCreate(BaseModel):
    """记一笔银行借款 → 银行池 IN。"""
    project_id: UUID
    amount: Decimal = Field(gt=0)
    transaction_date: date
    bank_id: UUID | None = None
    note: str | None = None
    idempotency_key: str | None = None


class BankRepayCreate(BaseModel):
    """还银行 → 银行池 OUT（余额不足拦截）。"""
    project_id: UUID
    amount: Decimal = Field(gt=0)
    transaction_date: date
    bank_id: UUID | None = None
    note: str | None = None
    idempotency_key: str | None = None


class PrepaymentCreate(BaseModel):
    """预付：现金池(from_pool) OUT + 预付款池(挂账) IN。"""
    project_id: UUID
    amount: Decimal = Field(gt=0)
    transaction_date: date
    contract_id: UUID | None = None
    from_pool: Literal["OWN", "LEASING", "BANK"] = "BANK"  # 从哪个现金池预付
    note: str | None = None
    idempotency_key: str | None = None


class PrepaymentRefund(BaseModel):
    """预付退回（金租放款后供应商退回）：预付款池 OUT + 现金回到 to_pool IN。"""
    project_id: UUID
    amount: Decimal = Field(gt=0)
    transaction_date: date
    to_pool: Literal["OWN", "LEASING", "BANK"] = "BANK"
    note: str | None = None
    idempotency_key: str | None = None


class PrepaymentOffset(BaseModel):
    """预付核销（拿采购发票）：预付款池 OUT，抵减应付（不涉现金）。"""
    project_id: UUID
    amount: Decimal = Field(gt=0)
    transaction_date: date
    invoice_id: UUID | None = None
    contract_id: UUID | None = None
    note: str | None = None
    idempotency_key: str | None = None
