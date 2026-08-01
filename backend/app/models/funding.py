"""资金置换记录 — 银行流贷/自有资金垫付 → 金租放款置换跟踪。"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class FundingReplacement(UUIDPK, TimestampMixin, Base):
    __tablename__ = "funding_replacements"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    leasing_process_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leasing_processes.id"), nullable=True)
    original_txn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=False)
    replacement_txn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    source_type_replaced: Mapped[str] = mapped_column(String(20), nullable=False)  # 银行流贷 / 自有资金
    replacement_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="已置换", nullable=False)  # 已置换 / 已撤销
