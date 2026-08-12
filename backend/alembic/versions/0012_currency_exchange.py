"""币种与汇率（二期 W5-6）：3 新表 + 4 表加币种/汇率字段（全 nullable，纯加法）。

新表：currencies / exchange_rates / exchange_gain_loss_rules。
加列：contracts(+currency_code+booked_rate)、invoices(+currency_code+invoice_rate)、
      billings(+currency_code+booked_rate)、capital_transactions(+currency_code+settlement_rate+base_amount)。
CHECK  widening：capital_transactions.source_type + '汇兑损益'（只扩不收窄，含全部旧 9 枚举）。
无数据迁移 → 真·无损可逆（downgrade 反序 DROP；source_type CHECK 回旧 9 枚举——'汇兑损益' 行
只可能由本阶段核销钩子产生，downgrade 前先 DELETE guard，同 0011 范式）。
与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，test_migration_parity 守护）。

Revision ID: 0012_currency_exchange
Revises: 0011_revenue_judge_fields
Create Date: 2026-08-12
"""
from alembic import op

revision = "0012_currency_exchange"
down_revision = "0011_revenue_judge_fields"
branch_labels = None
depends_on = None

_CT_SOURCE_OLD = "('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款','归还流贷','归还自有')"
_CT_SOURCE_NEW = "('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款','归还流贷','归还自有','汇兑损益')"


def upgrade() -> None:
    # —— 币种主数据 ——
    op.execute("""
        CREATE TABLE currencies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(10) NOT NULL,
            name VARCHAR(50) NOT NULL,
            symbol VARCHAR(10),
            is_base BOOLEAN NOT NULL DEFAULT FALSE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_currencies_code ON currencies(code) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_currencies_updated BEFORE UPDATE ON currencies FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 汇率表（rate 全精度 DECIMAL(18,8)，取值=最近不未来） ——
    op.execute("""
        CREATE TABLE exchange_rates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            from_currency VARCHAR(10) NOT NULL,
            to_currency VARCHAR(10) NOT NULL,
            rate_type VARCHAR(20) NOT NULL DEFAULT '中间价',
            rate DECIMAL(18,8) NOT NULL CHECK (rate > 0),
            effective_date DATE NOT NULL,
            source VARCHAR(50),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_fx_rates_lookup ON exchange_rates(from_currency, to_currency, rate_type, effective_date DESC) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_fx_rates_updated BEFORE UPDATE ON exchange_rates FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 汇兑损益科目规则 ——
    op.execute("""
        CREATE TABLE exchange_gain_loss_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scenario VARCHAR(50) NOT NULL,
            gl_account_code VARCHAR(50) NOT NULL,
            description VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_fxgl_scenario ON exchange_gain_loss_rules(scenario) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_fxgl_updated BEFORE UPDATE ON exchange_gain_loss_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 现有 4 表加币种/汇率字段（全 nullable；NULL=人民币，存量语义不变） ——
    op.execute("ALTER TABLE contracts ADD COLUMN currency_code VARCHAR(10)")
    op.execute("ALTER TABLE contracts ADD COLUMN booked_rate DECIMAL(18,8)")
    op.execute("ALTER TABLE invoices ADD COLUMN currency_code VARCHAR(10)")
    op.execute("ALTER TABLE invoices ADD COLUMN invoice_rate DECIMAL(18,8)")
    op.execute("ALTER TABLE billings ADD COLUMN currency_code VARCHAR(10)")
    op.execute("ALTER TABLE billings ADD COLUMN booked_rate DECIMAL(18,8)")
    op.execute("ALTER TABLE capital_transactions ADD COLUMN currency_code VARCHAR(10)")
    op.execute("ALTER TABLE capital_transactions ADD COLUMN settlement_rate DECIMAL(18,8)")
    op.execute("ALTER TABLE capital_transactions ADD COLUMN base_amount DECIMAL(18,2)")

    # —— source_type CHECK 扩 '汇兑损益'（只扩不收窄；约束名 capital_transactions_source_type_check 默认命名） ——
    op.execute("ALTER TABLE capital_transactions DROP CONSTRAINT IF EXISTS capital_transactions_source_type_check")
    op.execute(f"ALTER TABLE capital_transactions ADD CONSTRAINT capital_transactions_source_type_check CHECK (source_type IN {_CT_SOURCE_NEW})")


def downgrade() -> None:
    """反序 DROP（0012 无数据迁移）。source_type CHECK 收窄前先清 '汇兑损益' 流水（0011 guard 范式）。"""
    op.execute("DELETE FROM capital_transactions WHERE source_type = '汇兑损益'")
    op.execute("ALTER TABLE capital_transactions DROP CONSTRAINT IF EXISTS capital_transactions_source_type_check")
    op.execute(f"ALTER TABLE capital_transactions ADD CONSTRAINT capital_transactions_source_type_check CHECK (source_type IN {_CT_SOURCE_OLD})")
    op.execute("ALTER TABLE capital_transactions DROP COLUMN IF EXISTS base_amount")
    op.execute("ALTER TABLE capital_transactions DROP COLUMN IF EXISTS settlement_rate")
    op.execute("ALTER TABLE capital_transactions DROP COLUMN IF EXISTS currency_code")
    op.execute("ALTER TABLE billings DROP COLUMN IF EXISTS booked_rate")
    op.execute("ALTER TABLE billings DROP COLUMN IF EXISTS currency_code")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS invoice_rate")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS currency_code")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS booked_rate")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS currency_code")
    op.execute("DROP TRIGGER IF EXISTS trg_fxgl_updated ON exchange_gain_loss_rules")
    op.execute("DROP TABLE IF EXISTS exchange_gain_loss_rules")
    op.execute("DROP TRIGGER IF EXISTS trg_fx_rates_updated ON exchange_rates")
    op.execute("DROP TABLE IF EXISTS exchange_rates")
    op.execute("DROP TRIGGER IF EXISTS trg_currencies_updated ON currencies")
    op.execute("DROP TABLE IF EXISTS currencies")
