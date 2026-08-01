import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Asset(UUIDPK, TimestampMixin, Base):
    __tablename__ = "assets"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    equipment_model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipment_models.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_original_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_original_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    residual_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.10"), nullable=False)
    residual_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    depreciable_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    annual_depreciation: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    monthly_depreciation: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="折旧中", nullable=False)
