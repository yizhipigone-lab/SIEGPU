from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

PolicyType = Literal["运输险", "财产险"]
CostAllocation = Literal["资产原值", "长期待摊"]


class PolicyCreate(BaseModel):
    project_id: UUID
    policy_type: PolicyType
    device_ids: list[UUID] = Field(min_length=1)  # 设备粒度是 W7-8 核心
    policy_no: str | None = None
    insurer_id: UUID | None = None
    insured_amount: Decimal | None = Field(None, ge=0)
    premium_rate: Decimal | None = Field(None, ge=0, lt=1)
    start_date: date | None = None
    end_date: date | None = None
    cost_allocation: CostAllocation | None = None
    amortization_months: int | None = Field(None, gt=0)


class PolicyOut(BaseModel):
    id: UUID
    project_id: UUID
    batch_id: UUID | None
    policy_type: str
    policy_no: str | None
    insurer_id: UUID | None
    insured_amount: Decimal | None
    premium_rate: Decimal | None
    premium_amount: Decimal | None
    start_date: date | None
    end_date: date | None
    status: str
    trigger_event: str | None
    cost_allocation: str | None
    amortization_months: int | None
    collected_at: datetime | None
    claims: list | None
    created_at: datetime
    model_config = {"from_attributes": True}


class PolicyDeviceOut(BaseModel):
    id: UUID
    device_id: UUID
    allocated_amount: Decimal
    sn: str | None = None  # 端点填充（展示友好）
    model_config = {"from_attributes": True}


class ClaimIn(BaseModel):
    claim_date: date
    amount: Decimal = Field(gt=0)
    description: str | None = None


class AmortizationRow(BaseModel):
    period: int
    amount: Decimal


class ConfigIn(BaseModel):
    policy_type: PolicyType
    default_rate: Decimal | None = Field(None, ge=0, lt=1)
    insured_ratio: Decimal | None = Field(None, ge=0)
    insurer_id: UUID | None = None
    cost_allocation: CostAllocation | None = None
    active: bool = True


class ConfigOut(BaseModel):
    id: UUID
    policy_type: str
    default_rate: Decimal | None
    insured_ratio: Decimal | None
    insurer_id: UUID | None
    cost_allocation: str | None
    active: bool
    model_config = {"from_attributes": True}
