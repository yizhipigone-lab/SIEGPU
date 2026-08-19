"""合同类型 + 金额含税化（四期 W4）：contracts + biz_type / amount_incl_tax / lease_months。

- biz_type：合同业务类型（算力租赁/转售/服务），CHECK 容 NULL（存量不强制）。
- amount_incl_tax：合同金额（含税）。amount 仍为不含税口径（下游 invoice/对账/报表全部按不含税用 c.amount），
  故本列纯加法，存量按 含税 = round(amount*(1+tax_rate), 2) 回填，下游核算零改动。
- lease_months：租期(月)，仅算力租赁填写。
不加 NOT NULL、不改旧列 → 真·无损可逆（downgrade 直接 DROP COLUMN）。
与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，test_migration_parity 守护）。

Revision ID: 0021_contract_biz_type
Revises: 0020_sales_batch_acceptance
Create Date: 2026-08-19
"""
from alembic import op

revision = "0021_contract_biz_type"
down_revision = "0020_sales_batch_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS biz_type VARCHAR(20) CHECK (biz_type IS NULL OR biz_type IN ('算力租赁','转售','服务'))")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS amount_incl_tax DECIMAL(18,2) CHECK (amount_incl_tax IS NULL OR amount_incl_tax >= 0)")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS lease_months INTEGER CHECK (lease_months IS NULL OR lease_months >= 1)")
    # 存量回填：含税 = 不含税 × (1+税率)（amount 现值为不含税，见前端历史标签「合同金额(不含税,元)」）
    op.execute("UPDATE contracts SET amount_incl_tax = ROUND(amount * (1 + tax_rate), 2) WHERE amount_incl_tax IS NULL AND amount IS NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS lease_months")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS amount_incl_tax")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS biz_type")
