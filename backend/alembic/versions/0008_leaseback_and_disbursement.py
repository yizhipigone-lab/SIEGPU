"""售后回租长期应付款 + 放款阈值/幂等哨兵 + 预付款结转标记（一期 W7-8）。

- long_term_payables 新表（per-device 唯一）：回租出售时确认；carrying/gain_loss/paid 为钩子位（不分录）。
- orders：+disbursement_threshold_pct（默认 100，0-100 CHECK，应用层÷100）、+disbursement_todo_process_id（达阈值自动建 leasing 的幂等哨兵）。
- devices：+prepayment_settled（回租出售预付款结转标记）。
- audit_logs.action CHECK 扩 LEASEBACK_SALE（旧 17 枚举全保留，**不收窄**）。

纯加列/加表，无破坏性数据迁移（与 0007 批量资产拆分类不同）→ 真·无损可逆。
与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，一致性由 test_migration_parity 守护）。

Revision ID: 0008_leaseback
Revises: 0007_asset_per_device
Create Date: 2026-08-07
"""
from alembic import op

revision = "0008_leaseback"
down_revision = "0007_asset_per_device"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- long_term_payables 新表（per-device 唯一） ----------
    op.execute("""
        CREATE TABLE long_term_payables (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            leasing_process_id UUID NOT NULL REFERENCES leasing_processes(id),
            device_id UUID NOT NULL REFERENCES devices(id),
            supplier_id UUID NOT NULL REFERENCES suppliers(id),
            principal_amount DECIMAL(18,2) NOT NULL CHECK (principal_amount >= 0),
            carrying_amount DECIMAL(18,2) CHECK (carrying_amount >= 0),
            sale_gain_loss DECIMAL(18,2),
            original_end_date DATE,
            paid_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
            status VARCHAR(20) NOT NULL DEFAULT '已确认' CHECK (status IN ('已确认','部分偿还','已结清','已撤销')),
            confirm_date DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_ltp_device ON long_term_payables(device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_ltp_process ON long_term_payables(leasing_process_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_ltp_updated BEFORE UPDATE ON long_term_payables FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # ---------- orders：+放款阈值（百分比，应用层÷100） +幂等哨兵 ----------
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN disbursement_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 100
                CHECK (disbursement_threshold_pct BETWEEN 0 AND 100),
            ADD COLUMN disbursement_todo_process_id UUID REFERENCES leasing_processes(id)
    """)

    # ---------- devices：+预付款结转标记 ----------
    op.execute("ALTER TABLE devices ADD COLUMN prepayment_settled BOOLEAN NOT NULL DEFAULT FALSE")

    # ---------- audit_logs.action CHECK 扩 LEASEBACK_SALE（不收窄；约束名 0004 已确认为 audit_logs_action_check） ----------
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute("""
        ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (action IN (
            'CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE',
            'ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD',
            'DISBURSE','CAPITAL_TXN','LIGHT_ON','ALLOCATE','ALLOCATE_RETURN','LEASEBACK_SALE'))
    """)


def downgrade() -> None:
    """纯反序 DROP（0008 无数据迁移，真无损可逆）。"""
    # audit_logs CHECK 回旧 17 枚举
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute("""
        ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (action IN (
            'CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE',
            'ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD',
            'DISBURSE','CAPITAL_TXN','LIGHT_ON','ALLOCATE','ALLOCATE_RETURN'))
    """)
    op.execute("ALTER TABLE devices DROP COLUMN IF EXISTS prepayment_settled")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS disbursement_todo_process_id")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS disbursement_threshold_pct")
    op.execute("DROP TRIGGER IF EXISTS trg_ltp_updated ON long_term_payables")
    op.execute("DROP INDEX IF EXISTS idx_ltp_process")
    op.execute("DROP INDEX IF EXISTS uq_ltp_device")
    op.execute("DROP TABLE IF EXISTS long_term_payables")
