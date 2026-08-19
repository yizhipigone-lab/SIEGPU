from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

PaymentFreq = Literal["月", "季", "半年"]
RepaymentMethod = Literal["等额本息", "等额本金"]


class LeasingProcessCreate(BaseModel):
    project_id: UUID
    supplier_id: UUID
    total_amount: Decimal = Field(gt=0)
    annual_rate: Decimal | None = Field(None, ge=0, lt=1)  # 小数，0~1
    term_periods: int | None = Field(None, gt=0)
    payment_freq: PaymentFreq | None = None
    repayment_method: RepaymentMethod | None = None
    start_date: date | None = None
    notes: str | None = None
    leasing_mode: Literal["自有", "直租", "售后回租"] | None = None
    financing_type: Literal["金租直租", "金租回租", "银行流贷", "项目贷款"] | None = None
    materials: dict | None = None


class LeasingProcessOut(BaseModel):
    id: UUID
    project_id: UUID
    supplier_id: UUID
    total_amount: Decimal
    status: str
    disbursement_date: date | None
    plan_generated: bool
    leasing_mode: str | None = None
    financing_type: str | None = None
    materials: dict | None = None  # W7-8：融资分类材料（合同/发票/权属等）

    model_config = {"from_attributes": True}


class LeasingNodeOut(BaseModel):
    id: UUID
    node_name: str
    seq: int
    status: str
    planned_date: date | None
    actual_date: date | None
    stuck_reason: str | None

    model_config = {"from_attributes": True}


class LeasingProcessDetail(BaseModel):
    id: UUID
    project_id: UUID
    supplier_id: UUID
    total_amount: Decimal
    status: str
    disbursement_date: date | None
    plan_generated: bool
    leasing_mode: str | None = None  # W7-8：融资分类三字段回显
    financing_type: str | None = None
    materials: dict | None = None
    nodes: list[LeasingNodeOut]


class NodeAdvance(BaseModel):
    status: Literal["进行中", "已完成", "卡住"]
    actual_date: date | None = None
    stuck_reason: str | None = None


class DisburseRequest(BaseModel):
    actual_disbursement_amount: Decimal = Field(gt=0)
    disbursement_date: date
    note: str | None = None


class DisbursementCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    disbursement_date: date
    acceptance_id: UUID
    note: str | None = None


class DisbursementOut(BaseModel):
    id: UUID
    process_id: UUID
    acceptance_id: UUID | None = None
    amount: Decimal
    disbursement_date: date
    note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
