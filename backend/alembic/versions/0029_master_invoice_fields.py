"""0029 S11：供应商/客户开票信息与银行账号字段（缺陷#22，纯加法 nullable）。"""
from alembic import op

revision = "0029_master_invoice_fields"
down_revision = "0028_prepayments"
branch_labels = None
depends_on = None

SUPPLIER_COLS = (
    ("tax_no", "VARCHAR(50)"),
    ("invoice_title", "VARCHAR(200)"),
    ("bank_name", "VARCHAR(100)"),
    ("address", "VARCHAR(200)"),
)
CUSTOMER_COLS = (
    ("tax_no", "VARCHAR(50)"),
    ("invoice_title", "VARCHAR(200)"),
    ("bank_name", "VARCHAR(100)"),
    ("bank_account", "TEXT"),
)


def upgrade():
    for col, ddl in SUPPLIER_COLS:
        op.execute(f"ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS {col} {ddl};")
    for col, ddl in CUSTOMER_COLS:
        op.execute(f"ALTER TABLE customers ADD COLUMN IF NOT EXISTS {col} {ddl};")


def downgrade():
    for col, _ in CUSTOMER_COLS:
        op.execute(f"ALTER TABLE customers DROP COLUMN IF EXISTS {col};")
    for col, _ in SUPPLIER_COLS:
        op.execute(f"ALTER TABLE suppliers DROP COLUMN IF EXISTS {col};")
