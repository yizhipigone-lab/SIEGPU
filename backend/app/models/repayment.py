import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Repayment(UUIDPK, TimestampMixin, Base):
    __tablename__ = "repayments"

    leasing_process_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leasing_processes.id"), nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    planned_interest: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_principal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    actual_interest: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    capital_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("capital_transactions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="待还", nullable=False)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("repayments.id"), nullable=True)
