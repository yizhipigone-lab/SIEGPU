"""资金池分池（四期 W4 期1）：capital_transactions + pool 列 + source_type 扩枚举 + 存量回填。

- pool：资金池归属（OWN 自有 / LEASING 金租 / BANK 银行 / PREPAY 预付款挂账），默认 OWN。
  各池余额 = ΣIN − ΣOUT（按 project_id + pool 分组）；PREPAY 池余额 = 当前挂账预付总额。
- source_type CHECK 扩 2 个新动作：'预付'（PREPAY 池挂账/退回/核销，direction+category 区分）、
  '归还银行'（手动还银行，BANK 池 OUT；区别于置换引擎自动产生的 '归还流贷' IN）。
- 存量回填：金租融资→LEASING；银行流贷/归还流贷→BANK；其余保持 OWN。
- 分池不回溯历史资金去向（各池余额自启用时点起对增量准确）。
与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，test_migration_parity 守护）。

Revision ID: 0022_capital_pools
Revises: 0021_contract_biz_type
Create Date: 2026-08-19
"""
from alembic import op

revision = "0022_capital_pools"
down_revision = "0021_contract_biz_type"
branch_labels = None
depends_on = None

# 旧 10 枚举 + 新 2 枚举（'预付'、'归还银行'）
_SOURCE_TYPES_OLD = "('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款','归还流贷','归还自有','汇兑损益')"
_SOURCE_TYPES_NEW = "('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款','归还流贷','归还自有','汇兑损益','预付','归还银行')"


def upgrade() -> None:
    # 1) pool 列（NOT NULL DEFAULT 'OWN'，纯加法）
    op.execute("ALTER TABLE capital_transactions ADD COLUMN IF NOT EXISTS pool VARCHAR(20) NOT NULL DEFAULT 'OWN' CHECK (pool IN ('OWN','LEASING','BANK','PREPAY'))")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ct_pool ON capital_transactions(project_id, pool) WHERE deleted_at IS NULL")

    # 2) source_type CHECK 扩枚举（先 DROP 旧约束再 ADD 新约束）
    op.execute("ALTER TABLE capital_transactions DROP CONSTRAINT IF EXISTS capital_transactions_source_type_check")
    op.execute(f"ALTER TABLE capital_transactions ADD CONSTRAINT capital_transactions_source_type_check CHECK (source_type IN {_SOURCE_TYPES_NEW})")

    # 3) 存量回填 pool
    op.execute("UPDATE capital_transactions SET pool='LEASING' WHERE source_type='金租融资'")
    op.execute("UPDATE capital_transactions SET pool='BANK' WHERE source_type IN ('银行流贷','归还流贷','归还银行')")
    # 其余保持默认 OWN（自有资金/租金收入/调配/还款/汇兑损益/预付 等）


def downgrade() -> None:
    op.execute("ALTER TABLE capital_transactions DROP CONSTRAINT IF EXISTS capital_transactions_source_type_check")
    op.execute(f"ALTER TABLE capital_transactions ADD CONSTRAINT capital_transactions_source_type_check CHECK (source_type IN {_SOURCE_TYPES_OLD})")
    op.execute("DROP INDEX IF EXISTS idx_ct_pool")
    op.execute("ALTER TABLE capital_transactions DROP COLUMN IF EXISTS pool")
