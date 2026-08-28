"""0030 S8：放款模式（入池/直付）+ 置换归还日（缺陷#12/#13，纯加法 nullable）。"""
from alembic import op

revision = "0030_disbursement_mode"
down_revision = "0029_master_invoice_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE leasing_disbursements ADD COLUMN IF NOT EXISTS mode VARCHAR(20) NOT NULL DEFAULT '入池';")
    op.execute("ALTER TABLE leasing_disbursements ADD COLUMN IF NOT EXISTS replacement_date DATE;")


def downgrade():
    op.execute("ALTER TABLE leasing_disbursements DROP COLUMN IF EXISTS replacement_date;")
    op.execute("ALTER TABLE leasing_disbursements DROP COLUMN IF EXISTS mode;")
