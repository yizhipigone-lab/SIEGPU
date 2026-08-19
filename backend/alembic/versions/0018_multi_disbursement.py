"""金租分次放款：leasing_disbursements + repayments.disbursement_id + 老数据回填。

Revision ID: 0018_multi_disbursement
Revises: 0017_return_orders
Create Date: 2026-08-19
"""
from alembic import op

revision = "0018_multi_disbursement"
down_revision = "0017_return_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE leasing_disbursements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            process_id UUID NOT NULL REFERENCES leasing_processes(id),
            amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
            disbursement_date DATE NOT NULL,
            note TEXT,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_disb_process ON leasing_disbursements(process_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_disb_updated BEFORE UPDATE ON leasing_disbursements FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    op.execute("ALTER TABLE repayments ADD COLUMN IF NOT EXISTS disbursement_id UUID REFERENCES leasing_disbursements(id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_repay_disb ON repayments(disbursement_id) WHERE deleted_at IS NULL")

    # 老数据回填：已放款的单笔 process → 回填一条放款记录，并把其还款计划挂上去
    op.execute("""
        INSERT INTO leasing_disbursements (id, process_id, amount, disbursement_date, created_at, updated_at)
        SELECT gen_random_uuid(), id, actual_disbursement_amount, disbursement_date, now(), now()
        FROM leasing_processes
        WHERE plan_generated = TRUE AND actual_disbursement_amount IS NOT NULL AND disbursement_date IS NOT NULL
    """)
    op.execute("""
        UPDATE repayments r
        SET disbursement_id = d.id
        FROM leasing_disbursements d
        WHERE d.process_id = r.leasing_process_id
          AND r.disbursement_id IS NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE repayments DROP COLUMN IF EXISTS disbursement_id")
    op.execute("DROP TRIGGER IF EXISTS trg_disb_updated ON leasing_disbursements")
    op.execute("DROP TABLE IF EXISTS leasing_disbursements")
