import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Order(UUIDPK, TimestampMixin, Base):
    __tablename__ = "orders"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True)
    equipment_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("equipment_models.id"), nullable=True)  # 一期 W3-4：批次行可空
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 批次行可空
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 批次行可空
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 批次行可空
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="已下单", nullable=False)
    # 一期 W1-2：批次载体（orders 复用为批次表）
    is_batch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    batch_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    batch_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 批次聚合状态（独立字段，不复用 status）
    flow_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # batch/device/transfer-resale，首次判定后固化只升不降
    # 一期 W7-8：放款联动——阈值百分比（应用层÷100，默认 100%）+ 达阈值自动建 leasing_process 的幂等哨兵
    disbursement_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("100"), nullable=False)
    disbursement_todo_process_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leasing_processes.id"), nullable=True)


class DeliveryStage(UUIDPK, TimestampMixin, Base):
    __tablename__ = "delivery_stages"

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)  # 订货/到货/压测/运输在途/上架/点亮
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="未开始", nullable=False)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
