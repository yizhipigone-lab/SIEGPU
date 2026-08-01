"""验收记录 — 采购验收 + 销售验收，独立于交付阶段。"""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class AcceptanceRecord(UUIDPK, TimestampMixin, Base):
    __tablename__ = "acceptance_records"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    acceptance_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 采购验收 / 销售验收
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="待验收", nullable=False)
    inspector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acceptance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity_accepted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
