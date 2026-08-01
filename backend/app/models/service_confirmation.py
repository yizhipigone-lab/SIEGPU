"""客户算力服务确认单 — 计费→开票之间的客户确认门控。"""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class ServiceConfirmation(UUIDPK, TimestampMixin, Base):
    __tablename__ = "service_confirmations"

    billing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("billings.id"), unique=True, nullable=False)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confirmed_by_customer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="待确认", nullable=False)  # 待确认 / 已确认 / 有争议
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
