"""收入按开票确认（四期 W4 期2）：revenue_recognitions + invoice_id（开票驱动收入，幂等）。

- 新增 invoice_id（nullable FK→invoices），同一发票只出一张收入确认（部分唯一索引幂等）。
- 收入确认源从「计费 billing」改为「开票 invoice」：开票即出收入草稿（不含税=发票不含税），
  后续审批→确认流程不变。billing_id 列保留（历史数据）。
与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，test_migration_parity 守护）。

Revision ID: 0023_revenue_from_invoice
Revises: 0022_capital_pools
Create Date: 2026-08-19
"""
from alembic import op

revision = "0023_revenue_from_invoice"
down_revision = "0022_capital_pools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE revenue_recognitions ADD COLUMN IF NOT EXISTS invoice_id UUID REFERENCES invoices(id)")
    # 同一发票只出一张收入确认（幂等）；多 billing 仍各出各的（billing_id 不受影响）
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_rr_invoice ON revenue_recognitions(invoice_id) WHERE invoice_id IS NOT NULL AND deleted_at IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_rr_invoice")
    op.execute("ALTER TABLE revenue_recognitions DROP COLUMN IF EXISTS invoice_id")
