"""审计日志写入 — 扩 CHECK 加 DISBURSE/CAPITAL_TXN/LIGHT_ON/ALLOCATE/ALLOCATE_RETURN。

Revision ID: 0004_audit
Revises: 0003_wizard
Create Date: 2026-08-01
"""
from alembic import op

revision = "0004_audit"
down_revision = "0003_wizard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute("ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE','ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD','DISBURSE','CAPITAL_TXN','LIGHT_ON','ALLOCATE','ALLOCATE_RETURN'))")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute("ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE','ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD'))")
