"""付款管控 + 通用审批（二期 W11-12）：approvals / payment_requests / payment_settlements。

- approvals：通用审批（单级落地，level/max_level 留多级扩展）。
- payment_requests：付款申请三重管控（申请 → 审批 → 登记/付款）。
- payment_settlements：多对多核销核心——一笔流水 ↔ 多发票/多批次/多台设备（按金额逐台多行）；
  invoice_id 可空（待认领/预付款冲抵）；收款核销复用同表。
与 alembic 0015 / db/schema.sql 双写一致。
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Approval(UUIDPK, TimestampMixin, Base):
    __tablename__ = "approvals"

    biz_type: Mapped[str] = mapped_column(String(30), nullable=False)
    biz_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="待审批", nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaymentRequest(UUIDPK, TimestampMixin, Base):
    __tablename__ = "payment_requests"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(4), default="OUT", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    prepayment_offset: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="待审批", nullable=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("approvals.id"), nullable=True)
    capital_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class PaymentSettlement(UUIDPK, TimestampMixin, Base):
    __tablename__ = "payment_settlements"

    capital_transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
