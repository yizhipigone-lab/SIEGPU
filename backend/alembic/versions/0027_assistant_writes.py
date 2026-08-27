"""写操作确认卡（M-C）：assistant_confirm_tokens 新表 + audit CHECK 扩枚举 ASSISTANT_WRITE。

- 纯加表 + CHECK 只扩不窄（0008/0011 成熟模式）；downgrade 先 DELETE 新动作行再回缩。
- 与 db/schema.sql 双写一致（test_migration_parity 守护）。

Revision ID: 0027_assistant_writes
Revises: 0026_assistant_cognition
Create Date: 2026-08-27
"""
from alembic import op

_AUDIT_OLD = "('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE','ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD','DISBURSE','CAPITAL_TXN','LIGHT_ON','ALLOCATE','ALLOCATE_RETURN','LEASEBACK_SALE','REVENUE_JUDGE','REVENUE_OVERRIDE')"

revision = "0027_assistant_writes"
down_revision = "0026_assistant_cognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE assistant_confirm_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            action VARCHAR(32) NOT NULL,
            params_json JSONB NOT NULL,
            impact_amount DECIMAL(18,2),
            warnings JSONB,
            idempotency_key VARCHAR(128) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            result_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_asst_ct_user_used ON assistant_confirm_tokens(user_id, used_at) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_asst_ct_updated BEFORE UPDATE ON assistant_confirm_tokens FOR EACH ROW EXECUTE FUNCTION set_updated_at()")
    # audit CHECK：20 枚举 → +ASSISTANT_WRITE（只扩不窄）
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute(f"ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (action IN {_AUDIT_OLD.replace(')', ',\'ASSISTANT_WRITE\'))')}")


def downgrade() -> None:
    """先清 ASSISTANT_WRITE 行再回缩 CHECK（防收窄失败），纯反序 DROP。"""
    op.execute("DELETE FROM audit_logs WHERE action = 'ASSISTANT_WRITE'")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute(f"ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (action IN {_AUDIT_OLD})")
    op.execute("DROP TRIGGER IF EXISTS trg_asst_ct_updated ON assistant_confirm_tokens")
    op.execute("DROP INDEX IF EXISTS idx_asst_ct_user_used")
    op.execute("DROP TABLE IF EXISTS assistant_confirm_tokens")