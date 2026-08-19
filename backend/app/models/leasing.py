import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class LeasingProcess(UUIDPK, TimestampMixin, Base):
    __tablename__ = "leasing_processes"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_disbursement_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    term_periods: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    payment_freq: Mapped[str | None] = mapped_column(String(12), nullable=True)  # 月/季/半年
    repayment_method: Mapped[str | None] = mapped_column(String(12), nullable=True)  # 等额本息/等额本金
    status: Mapped[str] = mapped_column(String(20), default="进行中", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    approval_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    disbursement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 一期 W1-2：模式/分类/材料归档
    leasing_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 自有/直租/售后回租
    financing_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 金租直租/金租回租/银行流贷/项目贷款
    materials: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class LeasingNode(UUIDPK, TimestampMixin, Base):
    __tablename__ = "leasing_nodes"

    process_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leasing_processes.id"), nullable=False)
    node_name: Mapped[str] = mapped_column(String(50), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="未开始", nullable=False)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    attachments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stuck_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LeasingDisbursement(UUIDPK, TimestampMixin, Base):
    """一笔放款记录（一次金租批准可多笔放款，每笔独立生成还款计划）。"""

    __tablename__ = "leasing_disbursements"

    process_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leasing_processes.id"), nullable=False)
    acceptance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("acceptance_records.id"), nullable=True)  # 关联哪一批采购验收（验收→订单→合同→项目血缘）
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    disbursement_date: Mapped[date] = mapped_column(Date, nullable=False)  # 实际放款日（还款期从这天起算）
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
