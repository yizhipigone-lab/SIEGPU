"""会话管理（VERA memory.py 的 DB 版）。

P0 口径（评审拍板）：不做滚动摘要——每次只带最近 6 轮（12 条）消息进上下文。
20 万 token/日配额 + 8 轮工具上限下，6 轮窗口不会爆；摘要留 P1。
channel = 会话线标识（默认 "main"）；「新对话」= 软删当前 channel 会话，下次提问新建。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.assistant import AssistantMessage, AssistantSession

HISTORY_ROUNDS = 6  # 最近 6 轮（user+assistant 各 6 条）


def get_or_create_session(db: Session, user_id, channel: str = "main",
                          page_context: str | None = None) -> AssistantSession:
    """取 (user, channel) 的活跃会话；没有则新建。"""
    s = db.execute(
        select(AssistantSession).where(
            AssistantSession.user_id == user_id,
            AssistantSession.channel == channel,
        )
    ).scalars().first()
    if s is None:
        s = AssistantSession(user_id=user_id, channel=channel, page_context=page_context)
        db.add(s)
        db.flush()
    elif page_context:
        s.page_context = page_context
    return s


def load_history(db: Session, session_id, rounds: int = HISTORY_ROUNDS) -> list[dict]:
    """最近 N 轮 → OpenAI messages 格式（只取 user/assistant，tool 消息不进历史）。"""
    rows = db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.session_id == session_id,
               AssistantMessage.role.in_(("user", "assistant")))
        .order_by(AssistantMessage.created_at.desc())
        .limit(rounds * 2)
    ).scalars().all()
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


def save_message(db: Session, session_id, role: str, content: str,
                 tool_calls: dict | None = None, tokens_used: int = 0) -> AssistantMessage:
    m = AssistantMessage(session_id=session_id, role=role, content=content or "",
                         tool_calls=tool_calls, tokens_used=tokens_used)
    db.add(m)
    db.flush()
    return m


def tokens_today(db: Session, user_id) -> int:
    """单用户当日 token 消耗（日配额闸门的读数）。"""
    today_start = datetime.combine(date.today(), datetime.min.time())
    return int(db.execute(
        select(func.coalesce(func.sum(AssistantMessage.tokens_used), 0))
        .where(AssistantMessage.session_id.in_(
            select(AssistantSession.id).where(AssistantSession.user_id == user_id)),
            AssistantMessage.created_at >= today_start)
    ).scalar() or 0)


def quota_left(db: Session, user_id) -> int:
    return max(0, settings.assistant_daily_token_quota - tokens_today(db, user_id))


def reset_session(db: Session, user_id, channel: str = "main") -> bool:
    """软删当前 channel 会话（下一条消息开新会话）。返回是否有会话被清。"""
    s = db.execute(
        select(AssistantSession).where(
            AssistantSession.user_id == user_id,
            AssistantSession.channel == channel,
        )
    ).scalars().first()
    if not s:
        return False
    s.deleted_at = datetime.now()
    db.flush()
    return True

def load_history_full(db: Session, session_id, rounds: int = 25) -> list[dict]:
    """历史回放（含 id/feedback，供前端渲染反馈按钮状态）。"""
    rows = db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.session_id == session_id,
               AssistantMessage.role.in_(("user", "assistant")))
        .order_by(AssistantMessage.created_at.desc())
        .limit(rounds * 2)
    ).scalars().all()
    rows.reverse()
    return [{"id": str(r.id), "role": r.role, "content": r.content,
             "feedback": r.feedback} for r in rows]