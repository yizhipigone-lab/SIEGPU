"""智能助手（对话大脑）会话与消息表（2026-08-27 P0）。

- assistant_sessions：一个 (user_id, channel) 一条会话线（VERA memory.py channel 映射的 DB 版）。
- assistant_messages：消息流水，同时承担审计与「最近 N 轮 + 滚动摘要」的原料；
  tokens_used 用于日配额闸门（engine.check_quota）。
与 alembic 0024 / db/schema.sql 双写一致（test_migration_parity 守护）。
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text
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

class AssistantCognition(UUIDPK, TimestampMixin, Base):
    """长期认知沉淀（M-A）：实体别名/口径偏好，per-user。

    纪律（VERA memory 同源）：只存认知/口径，绝不含金额数字（红线硬校验在 memory 层）。
    置信度模型：user 教授=100；自动捕获=50；用到且未被 👎 → usage_count+1；
    用到且被 👎 → confidence-30，≤0 软删（归因依赖 assistant_messages.tool_calls.cognition_used）。"""

    __tablename__ = "assistant_cognition"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)   # entity_alias/glossary_pref/query_hint
    key: Mapped[str] = mapped_column(String(200), nullable=False)   # 检索键，如「七号项目」
    value: Mapped[str] = mapped_column(Text, nullable=False)        # 值，如「指项目 商机5090」
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="auto")  # auto/user
    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=50)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AssistantConfirmToken(UUIDPK, TimestampMixin, Base):
    """写操作确认令牌（M-C）：dry_run 生成、用户确认后原子认领执行。

    不变量：idempotency_key 唯一（单次执行兜底）；params_json 为服务端解析结果
    （执行以此为准，LLM 数字不采信）；used_at 认领即终态（取消也置 used_at，result_json 区分）。"""

    __tablename__ = "assistant_confirm_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)   # record_income/draft_billing/advance_step/allocate_funds
    params_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    impact_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)