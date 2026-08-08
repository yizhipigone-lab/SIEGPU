from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    project_id: UUID
    contract_id: UUID | None = None
    equipment_model_id: UUID
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    order_date: date | None = None
    expected_delivery_date: date | None = None
    is_batch: bool = False
    batch_name: str | None = None
    # W7-8 决策 2：放款阈值可配百分比（0-100）。缺省 None→服务层填 100（与列默认一致）。
    disbursement_threshold_pct: Decimal | None = Field(None, ge=0, le=100)


class DeliveryStageOut(BaseModel):
    id: UUID
    stage: str
    seq: int
    status: str
    planned_date: date | None
    actual_date: date | None
    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: UUID
    project_id: UUID
    # A2：orders 批次行 4 字段已放宽 nullable（批次订单无单台语义），响应 schema 须同步 Optional，
    # 否则 OrderDetail(total_amount=None) 序列化 → Pydantic ValidationError → 接口 500（W3-4 亲历 bug）。
    equipment_model_id: UUID | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None
    total_amount: Decimal | None = None
    status: str
    is_batch: bool = False
    batch_name: str | None = None
    batch_status: str | None = None
    flow_type: str | None = None
    # W7-8：放款阈值（百分比，0-100，默认 100）+ 达阈值自动建的 leasing_process 幂等哨兵。
    disbursement_threshold_pct: Decimal = Decimal("100")
    disbursement_todo_process_id: UUID | None = None
    model_config = {"from_attributes": True}


class OrderDetail(OrderOut):
    contract_id: UUID | None
    stages: list[DeliveryStageOut]


class StageAdvance(BaseModel):
    status: Literal["进行中", "已完成"]
    actual_date: date | None = None


class LightOnRequest(BaseModel):
    actual_date: date
