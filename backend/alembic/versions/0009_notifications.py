"""应用内消息提醒表（F1）：notifications。

纯加表（Notification 持久化 alert_service 结果，按用户扇出，各自已读独立）。
- 不动任何现有表，无数据迁移 → 真·无损可逆。
- 手写（不用 autogenerate）：当前 alembic check 因 fk_inv_billing 的 DEFERRED 漂移 FAILED，
  autogenerate 会把历史漂移卷进新迁移，故 0009 一律手写 op.execute 裸 SQL。
- 与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，test_migration_parity 守护）。

Revision ID: 0009_notifications
Revises: 0008_leaseback
Create Date: 2026-08-09
"""
from alembic import op

revision = "0009_notifications"
down_revision = "0008_leaseback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            kind VARCHAR(64) NOT NULL,
            ref_type VARCHAR(32),
            ref_id VARCHAR(64),
            title VARCHAR(120) NOT NULL,
            body VARCHAR(500) NOT NULL,
            level VARCHAR(16) NOT NULL DEFAULT '提示',
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    # 未读查询：WHERE user_id=? AND read_at IS NULL
    op.execute("CREATE INDEX idx_notif_user_read ON notifications(user_id, read_at) WHERE deleted_at IS NULL")
    # 近期列表：ORDER BY created_at DESC
    op.execute("CREATE INDEX idx_notif_user_created ON notifications(user_id, created_at DESC) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_notif_ref ON notifications(kind, ref_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_notifications_updated BEFORE UPDATE ON notifications FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    """纯反序 DROP（0009 仅加表，真无损可逆）。"""
    op.execute("DROP TRIGGER IF EXISTS trg_notifications_updated ON notifications")
    op.execute("DROP INDEX IF EXISTS idx_notif_ref")
    op.execute("DROP INDEX IF EXISTS idx_notif_user_created")
    op.execute("DROP INDEX IF EXISTS idx_notif_user_read")
    op.execute("DROP TABLE IF EXISTS notifications")
