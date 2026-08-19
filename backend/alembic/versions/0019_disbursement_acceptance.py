"""金租放款关联采购验收：leasing_disbursements.acceptance_id。

Revision ID: 0019_disbursement_acceptance
Revises: 0018_multi_disbursement
Create Date: 2026-08-19
"""
from alembic import op

revision = "0019_disbursement_acceptance"
down_revision = "0018_multi_disbursement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE leasing_disbursements ADD COLUMN IF NOT EXISTS acceptance_id UUID REFERENCES acceptance_records(id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_disb_acceptance ON leasing_disbursements(acceptance_id) WHERE deleted_at IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_disb_acceptance")
    op.execute("ALTER TABLE leasing_disbursements DROP COLUMN IF EXISTS acceptance_id")
