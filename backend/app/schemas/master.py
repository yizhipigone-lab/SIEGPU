from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------- suppliers ----------
class SupplierCreate(BaseModel):
    name: str
    type: Literal["设备供应商", "资金供应商", "其他"]
    contact_person: str | None = None
    contact_phone: str | None = None
    bank_account: str | None = None
    notes: str | None = None
    is_leasing_org: bool = False
    leasing_coop_modes: list[str] | None = None  # 合作模式：直租/回租


class SupplierOut(BaseModel):
    id: UUID
    name: str
    type: str
    contact_person: str | None
    contact_phone: str | None
    is_leasing_org: bool = False
    leasing_coop_modes: list[str] | None = None
    model_config = {"from_attributes": True}


# ---------- customers ----------
class CustomerCreate(BaseModel):
    name: str
    industry: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    credit_rating: str | None = None
    notes: str | None = None


class CustomerOut(BaseModel):
    id: UUID
    name: str
    industry: str | None
    contact_person: str | None
    credit_rating: str | None
    model_config = {"from_attributes": True}


# ---------- equipment_models ----------
class EquipmentModelCreate(BaseModel):
    name: str
    category: Literal["大卡", "小卡", "组网设备"]
    gpu_type: str | None = None
    gpu_count: int | None = Field(None, gt=0)
    memory: str | None = None
    unit_price_reference: Decimal | None = Field(None, ge=0)
    resource_attr: Literal["自购资产", "金租资产", "转售资源"] | None = None
    billing_modes: dict | None = None


class EquipmentModelOut(BaseModel):
    id: UUID
    name: str
    category: str
    gpu_type: str | None
    gpu_count: int | None
    memory: str | None
    unit_price_reference: Decimal | None
    resource_attr: str | None = None
    billing_modes: dict | None = None
    model_config = {"from_attributes": True}


# ---------- banks ----------
class BankCreate(BaseModel):
    name: str
    contact_person: str | None = None
    contact_phone: str | None = None
    credit_line: Decimal | None = Field(None, ge=0)
    annual_rate: Decimal | None = Field(None, ge=0, lt=1)  # 小数


class BankOut(BaseModel):
    id: UUID
    name: str
    contact_person: str | None
    credit_line: Decimal | None
    annual_rate: Decimal | None
    model_config = {"from_attributes": True}
