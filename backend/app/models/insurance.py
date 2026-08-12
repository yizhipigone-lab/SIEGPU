"""保险管理（二期 W7-8）：保单 + 保单设备分摊 + 投保配置。

硬约束：保费仅「点亮前」窗口可归集进资产原值（service 层校验 + collected_at 幂等留痕）；
点亮后一律长期待摊（不触动折旧算法）。与 alembic 0013 / db/schema.sql 双写一致。
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class InsurancePolicy(UUIDPK, TimestampMixin, Base):
    __tablename__ = "insurance_policies"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    policy_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 运输险/财产险
    policy_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    insurer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    insured_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)   # 保额
    premium_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)     # 费率（小数）
    premium_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)   # 保费=q2(保额×费率)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="待确认", nullable=False)
    trigger_event: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 在途/点亮/手工
    cost_allocation: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 资产原值/长期待摊
    amortization_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claims: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)


class InsurancePolicyDevice(UUIDPK, TimestampMixin, Base):
    """保单-设备分摊行：保费按设备 purchase_value 占比逐台分摊（末台吃尾差保合计精确）。"""
    __tablename__ = "insurance_policy_devices"

    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("insurance_policies.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)


class InsuranceConfig(UUIDPK, TimestampMixin, Base):
    """投保配置：险种默认费率/投保比例/承保人/归集口径（自动投保输入；无配置=不自动投保）。"""
    __tablename__ = "insurance_configs"

    policy_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 运输险/财产险
    default_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    insured_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    insurer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    cost_allocation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
