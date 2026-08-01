"""项目流程实例 — 每个项目一个 workflow 实例。"""
import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class ProjectWorkflow(UUIDPK, TimestampMixin, Base):
    __tablename__ = "project_workflows"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), unique=True, nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_templates.id"), nullable=True)
    steps: Mapped[dict] = mapped_column(JSONB, nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="进行中", nullable=False)  # 进行中 / 已完成 / 已暂停
