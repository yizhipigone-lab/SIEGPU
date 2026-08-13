"""采购退货（三期 §4.4）：return_orders / return_order_devices。
与 alembic 0017 / db/schema.sql 双写一致。"""
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class ReturnOrder(UUIDPK, TimestampMixin, Base):
    """退货单。状态机：退货申请→已出库→供应商已收货→已开红字发票→已退款核销（或 预付款已冲回）。"""
    __tablename__ = "return_orders"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    original_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    return_type: Mapped[str] = mapped_column(String(30), nullable=False)  # 到货不合格/压测不通过/合同终止
    status: Mapped[str] = mapped_column(String(30), default="退货申请", nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    prepayment_recover: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    red_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    refund_txn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ReturnOrderDevice(UUIDPK, TimestampMixin, Base):
    __tablename__ = "return_order_devices"

    return_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("return_orders.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
