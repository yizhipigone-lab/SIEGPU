"""智能助手（对话大脑 P0）：assistant_sessions + assistant_messages。

- 纯加表，不动任何现有表，无数据迁移 → 真无损可逆。
- 手写（不用 autogenerate），与 db/schema.sql 双写一致（conftest 用 schema.sql 建表，
  test_migration_parity 守护）。

Revision ID: 0024_assistant
Revises: 0023_revenue_from_invoice
Create Date: 2026-08-27
"""
from alembic import op

revision = "0024_assistant"
down_revision = "0023_revenue_from_invoice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE assistant_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            channel VARCHAR(64) NOT NULL DEFAULT 'main',
            title VARCHAR(200),
            page_context VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    # 一个用户一个 channel 一条会话线（软删部分唯一，沿用 notifications 的索引范式）
    op.execute("CREATE UNIQUE INDEX uq_asst_session_channel ON assistant_sessions(user_id, channel) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_asst_session_user ON assistant_sessions(user_id, updated_at DESC) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_asst_sessions_updated BEFORE UPDATE ON assistant_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    op.execute("""
        CREATE TABLE assistant_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES assistant_sessions(id),
            role VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','tool')),
            content TEXT NOT NULL DEFAULT '',
            tool_calls JSONB,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_asst_msg_session ON assistant_messages(session_id, created_at) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_asst_messages_updated BEFORE UPDATE ON assistant_messages FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    """纯反序 DROP（0024 仅加表，真无损可逆）。"""
    op.execute("DROP TRIGGER IF EXISTS trg_asst_messages_updated ON assistant_messages")
    op.execute("DROP TRIGGER IF EXISTS trg_asst_sessions_updated ON assistant_sessions")
    op.execute("DROP INDEX IF EXISTS idx_asst_msg_session")
    op.execute("DROP INDEX IF EXISTS idx_asst_session_user")
    op.execute("DROP INDEX IF EXISTS uq_asst_session_channel")
    op.execute("DROP TABLE IF EXISTS assistant_messages")
    op.execute("DROP TABLE IF EXISTS assistant_sessions")