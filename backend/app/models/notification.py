"""应用内消息提醒（F1）。

持久化 alert_service.compute_alerts 的结果，按用户分散（一人一行 → 各自已读独立）。
与 alembic 0009 / db/schema.sql 双写一致；仅应用内铃铛，不接邮件/企微。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Notification(UUIDPK, TimestampMixin, Base):
    __tablename__ = "notifications"

    # 收件人：告警按「活跃用户」全量扇出（内部小团队，人人可见财务/运营风险）；各自 read_at 独立。
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)        # 告警 code，如 REPAYMENT_OVERDUE
    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)   # repayment/contract/leasing/...（前端跳转用）
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 业务对象 id（字符串）
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="提示")  # 高危/警告/提示
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
