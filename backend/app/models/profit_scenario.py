"""盈利测算场景 — 存储测算参数与结果，支持测算 vs 实际对比。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class ProfitScenario(UUIDPK, TimestampMixin, Base):
    __tablename__ = "profit_scenarios"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    params_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_actual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
