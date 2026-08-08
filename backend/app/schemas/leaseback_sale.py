"""售后回租·回租出售 schema（一期 W7-8）。"""
from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class LeasebackSaleCreate(BaseModel):
    """回租出售入参（独立动作+按钮，决策 1）。"""
    sale_date: date
    leasing_org_id: UUID  # 金租机构（须 type=资金供应商）
    sale_price: Decimal = Field(..., ge=0)
    leasing_process_id: UUID  # 关联融资申请（载体）
    note: str | None = None


class LeasebackSaleOut(BaseModel):
    """回租出售结果：截断后账面价值 + 出售损益 + 关联对象 id。"""
    device_id: UUID
    asset_id: UUID
    operation_status: str  # 已处置
    off_balance_register_id: UUID
    long_term_payable_id: UUID
    carrying_amount: Decimal
    sale_gain_loss: Decimal
    prepayment_settled: bool
    model_config = {"from_attributes": True}
