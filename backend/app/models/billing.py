import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Billing(UUIDPK, TimestampMixin, Base):
    __tablename__ = "billings"
    __table_args__ = (
        # W5-6 H-1：计费唯一索引迁 device 维度（schema.sql/alembic 0007 一致；旧 order_id 维已弃）。
        # device_id IS NULL 的 legacy 订单维 billings 不被此索引挡（service 层 dup-check 兜底）。
        Index("uq_billing_period", "device_id", "period_index", unique=True,
              postgresql_where=text("deleted_at IS NULL AND device_id IS NOT NULL")),
        Index("uq_billing_idem", "idempotency_key", unique=True,
              postgresql_where=text("idempotency_key IS NOT NULL")),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    # W5-6：按台计费 billings 可无 purchase order（导入设备无订单）；v3.1 起 schema.sql 已 nullable，ORM 对齐
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    period_index: Mapped[int] = mapped_column(Integer, nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_in_period: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 含税
    amount_ex_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.13"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="未开", nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    capital_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=True)
    confirmation_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 待确认 / 已确认 / 有争议
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("billings.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)  # 一期 W1-2：按台计费
    # 二期 W5-6：币种与计费日记账汇率（nullable；NULL=人民币）
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    booked_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)


class Invoice(UUIDPK, TimestampMixin, Base):
    __tablename__ = "invoices"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(12), nullable=False)  # RECEIVABLE/PAYABLE
    invoice_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 含税
    amount_ex_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.13"), nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="待开", nullable=False)
    capital_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=True)
    billing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("billings.id"), nullable=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    reconciled_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    reconciled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reconciliation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 二期 W5-6：币种与开票日汇率（nullable；NULL=人民币）
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    invoice_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    # 二期 W11-12：进项侧认证/抵扣（nullable；NULL=未涉及进项流程）
    certification_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    certification_date: Mapped[date | None] = mapped_column(Date, nullable=True)


# v3.2: 已核销累计金额 = 关联核销流水金额合计（查询期计算，不落库列；InvoiceOut.matched_amount 由它填充）
# 二期 W11-12：payment_settlements 多对多核销同样计入（新核销路径不写 txn.invoice_id，两路径互斥不双计）
from app.models.capital import CapitalTransaction  # noqa: E402
from app.models.payment import PaymentSettlement  # noqa: E402

Invoice.matched_amount = column_property(
    select(func.coalesce(func.sum(CapitalTransaction.amount), 0))
    .where(
        CapitalTransaction.invoice_id == Invoice.id,
        CapitalTransaction.deleted_at.is_(None),
    )
    .correlate_except(CapitalTransaction)
    .scalar_subquery()
    +
    select(func.coalesce(func.sum(PaymentSettlement.amount), 0))
    .where(
        PaymentSettlement.invoice_id == Invoice.id,
        PaymentSettlement.deleted_at.is_(None),
    )
    .correlate_except(PaymentSettlement)
    .scalar_subquery()
)
