"""销售订单 — 销售合同下的分批次履约清单。"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
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
