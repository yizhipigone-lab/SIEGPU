"""长期认知沉淀（M-A）：assistant_cognition 新表（纯加法，无损可逆）。

- per-user；(user_id, kind, key) 部分唯一（软删态可重建）。
- 与 db/schema.sql 双写一致（test_migration_parity 守护）。

Revision ID: 0026_assistant_cognition
Revises: 0025_assistant_feedback
Create Date: 2026-08-27
"""
from alembic import op

revision = "0026_assistant_cognition"
down_revision = "0025_assistant_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE assistant_cognition (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            kind VARCHAR(20) NOT NULL CHECK (kind IN ('entity_alias','glossary_pref','query_hint')),
            key VARCHAR(200) NOT NULL,
            value TEXT NOT NULL,
            source VARCHAR(8) NOT NULL DEFAULT 'auto' CHECK (source IN ('auto','user')),
            confidence SMALLINT NOT NULL DEFAULT 50,
            usage_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_asst_cog_user_key ON assistant_cognition(user_id, kind, key) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_asst_cog_user ON assistant_cognition(user_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_asst_cog_updated BEFORE UPDATE ON assistant_cognition FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_asst_cog_updated ON assistant_cognition")
    op.execute("DROP INDEX IF EXISTS idx_asst_cog_user")
    op.execute("DROP INDEX IF EXISTS uq_asst_cog_user_key")
    op.execute("DROP TABLE IF EXISTS assistant_cognition")