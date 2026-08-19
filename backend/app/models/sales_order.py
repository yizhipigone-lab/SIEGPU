"""销售订单 — 销售合同下的分批次履约清单。

W4（销售分批次验收）：sales_orders 复用为「销售批次」载体（is_batch=True + batch_name），
设备通过 sales_batch_devices 挂到销售批次下（照采购侧 batch_devices 模式）。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class SalesOrder(UUIDPK, TimestampMixin, Base):
    __tablename__ = "sales_orders"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    equipment_model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipment_models.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_rent_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_monthly_rent: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="待交付", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # W4：销售批次载体（照采购侧 orders.is_batch/batch_name/batch_status）
    is_batch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    batch_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    batch_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 批次聚合状态（独立字段，不复用 status）


class SalesBatchDevice(UUIDPK, TimestampMixin, Base):
    """销售批次-设备组合关系（留痕）。同一台设备全局仅允许一条 active 记录（service 层强制）。"""

    __tablename__ = "sales_batch_devices"

    sales_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # 加入/移出
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    operated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
