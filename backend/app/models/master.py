from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Supplier(UUIDPK, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 设备供应商/资金供应商/其他
    contact_person: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 缺陷#22：开票信息 + 银行账号结构化（与现有系统对应）
    tax_no: Mapped[str | None] = mapped_column(String(50), nullable=True)       # 税号
    invoice_title: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 开票抬头
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)   # 开户行
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)     # 地址
    # 一期 W1-2：金租机构标记 + 合作模式
    is_leasing_org: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    leasing_coop_modes: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 直租/回租


class Customer(UUIDPK, TimestampMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    credit_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 缺陷#22：客户开票信息 + 银行账号
    tax_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(Text, nullable=True)


class EquipmentModel(UUIDPK, TimestampMixin, Base):
    __tablename__ = "equipment_models"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # 大卡/小卡/组网设备
    gpu_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gpu_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory: Mapped[str | None] = mapped_column(String(50), nullable=True)
    spec_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    unit_price_reference: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # 一期 W1-2：资源属性 + 计费模式
    resource_attr: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 自购资产/金租资产/转售资源
    billing_modes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 计费模式（按时/天/月）+ 基准单价


class Bank(UUIDPK, TimestampMixin, Base):
    __tablename__ = "banks"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    credit_line: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
