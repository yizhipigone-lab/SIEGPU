"""智能助手（对话大脑）会话与消息表（2026-08-27 P0）。

- assistant_sessions：一个 (user_id, channel) 一条会话线（VERA memory.py channel 映射的 DB 版）。
- assistant_messages：消息流水，同时承担审计与「最近 N 轮 + 滚动摘要」的原料；
  tokens_used 用于日配额闸门（engine.check_quota）。
与 alembic 0024 / db/schema.sql 双写一致（test_migration_parity 守护）。
"""
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class AssistantSession(UUIDPK, TimestampMixin, Base):
    __tablename__ = "assistant_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="main")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    page_context: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AssistantMessage(UUIDPK, TimestampMixin, Base):
    __tablename__ = "assistant_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assistant_sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant / tool
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feedback: Mapped[str | None] = mapped_column(String(8), nullable=True)  # up/down（体验包 #7）

class AssistantGap(UUIDPK, TimestampMixin, Base):
    """问题缺口表（体验包 #7）：👎 的问题自动落表，驱动后续补工具/补 KB——
    「让系统自己学习」的正经形态：缺口数据说话，不靠人肉反馈。"""

    __tablename__ = "assistant_gaps"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_head: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tools_used: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="user_downvote")
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False)