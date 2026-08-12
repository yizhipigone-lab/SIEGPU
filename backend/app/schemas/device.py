from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

LeasingMode = Literal["自有", "直租", "售后回租"]
Ownership = Literal["表内自有", "金租表外", "转售表外"]
DeviceStageName = Literal["订货", "在途", "到货", "己方压测", "上架", "客户压测", "点亮验收"]
StageStatus = Literal["未开始", "进行中", "已完成", "不合格"]


class DeviceCreate(BaseModel):
    sn: str | None = None  # 缺省自动生成 GPU-{yyyymm}-{seq5}
    project_id: UUID
    equipment_model_id: UUID
    order_id: UUID | None = None
    sales_contract_id: UUID | None = None
    supplier_id: UUID | None = None
    monthly_price: Decimal | None = Field(None, ge=0)
    config: dict | None = None
    leasing_mode: LeasingMode | None = None  # 缺省快照自项目
    purchase_value: Decimal | None = Field(None, ge=0)
    prepayment_amount: Decimal = Field(default=Decimal("0"), ge=0)
    ownership: Ownership | None = None


class DeviceUpdate(BaseModel):
    """可更新字段白名单（status/batch_id 不在此列：status 归状态机，批次走 batch-assign/remove）。"""

    sn: str | None = None
    order_id: UUID | None = None
    sales_contract_id: UUID | None = None
    supplier_id: UUID | None = None
    monthly_price: Decimal | None = Field(None, ge=0)
    config: dict | None = None
    leasing_mode: LeasingMode | None = None
    purchase_value: Decimal | None = Field(None, ge=0)
    prepayment_amount: Decimal | None = Field(None, ge=0)
    ownership: Ownership | None = None


class DeviceOut(BaseModel):
    id: UUID
    sn: str
    project_id: UUID
    order_id: UUID | None
    batch_id: UUID | None
    sales_contract_id: UUID | None
    equipment_model_id: UUID
    supplier_id: UUID | None
    monthly_price: Decimal | None
    config: dict | None
    leasing_mode: str | None
    purchase_value: Decimal | None
    prepayment_amount: Decimal
    status: str
    ownership: str | None
    prepayment_settled: bool = False  # W7-8：回租出售后置位（决策 3，仅标记）
    prepayment_settled_amount: Decimal | None = None  # 二期 W9-10：累计已结转/冲抵（D2 单源）
    model_config = {"from_attributes": True}


class BatchAssign(BaseModel):
    device_id: UUID
    batch_id: UUID


class BatchRemove(BaseModel):
    device_id: UUID


class BatchDeviceOut(BaseModel):
    id: UUID
    batch_id: UUID
    device_id: UUID
    action: str
    active: bool
    operated_by: UUID | None
    model_config = {"from_attributes": True}


class OffBalanceRegisterCreate(BaseModel):
    device_id: UUID
    register_type: Literal["金租直租", "售后回租", "转售"]
    leasing_process_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    note: str | None = None


class OffBalanceRegisterOut(BaseModel):
    id: UUID
    device_id: UUID
    register_type: str
    leasing_process_id: UUID | None
    start_date: date | None
    end_date: date | None
    note: str | None
    model_config = {"from_attributes": True}


# ---- 一期 W3-4：设备节点状态机 ----

class DeviceStageAdvance(BaseModel):
    """单台节点推进。stage+status 必填；actual_date/attachment_path/notes 可选。"""
    stage: DeviceStageName
    status: StageStatus
    actual_date: date | None = None
    attachment_path: str | None = Field(None, max_length=500)
    notes: str | None = None


class BatchAdvanceRequest(DeviceStageAdvance):
    """批量推进：批内所有 active 设备推进同一节点。"""
    batch_id: UUID


class DeviceStageOut(BaseModel):
    id: UUID
    device_id: UUID
    stage: str
    seq: int
    status: str
    planned_date: date | None
    actual_date: date | None
    attachment_path: str | None
    notes: str | None
    model_config = {"from_attributes": True}
