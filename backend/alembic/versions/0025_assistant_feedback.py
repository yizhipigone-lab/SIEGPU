"""助手反馈与问题缺口（体验包 #7）：assistant_messages + feedback 列；assistant_gaps 新表。

- messages 加列 nullable（存量行无感）；gaps 纯加表 → 无损可逆。
- 与 db/schema.sql 双写一致（test_migration_parity 守护）。

Revision ID: 0025_assistant_feedback
Revises: 0024_assistant
Create Date: 2026-08-27
"""
from alembic import op

revision = "0025_assistant_feedback"
down_revision = "0024_assistant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE assistant_messages ADD COLUMN IF NOT EXISTS feedback VARCHAR(8)")
    op.execute("""
        CREATE TABLE assistant_gaps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            question TEXT NOT NULL DEFAULT '',
            answer_head VARCHAR(200),
            tools_used JSONB,
            reason VARCHAR(32) NOT NULL DEFAULT 'user_downvote',
            resolved BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_asst_gap_user ON assistant_gaps(user_id, created_at DESC) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_asst_gaps_updated BEFORE UPDATE ON assistant_gaps FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_asst_gaps_updated ON assistant_gaps")
    op.execute("DROP INDEX IF EXISTS idx_asst_gap_user")
    op.execute("DROP TABLE IF EXISTS assistant_gaps")
    op.execute("ALTER TABLE assistant_messages DROP COLUMN IF EXISTS feedback")