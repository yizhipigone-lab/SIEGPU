"""合同深化 + 单据编号 + 金租规则（二期 W9-10）：4 新表 + devices 结转列 + contracts +6 字段。

新表：contract_amendments / contract_terminations / doc_number_rules / leasing_rule_configs。
加列：devices +prepayment_settled_amount（D2 裁定：预付款复用 devices 字段单源，不建 prepayments 表）；
      contracts +purchase_type/delivery_terms/warranty_terms/penalty_terms/prepayment_ratio/collection_account_type。
全 nullable 纯加法 → 真·无损可逆。与 db/schema.sql 双写一致（test_migration_parity 守护）。

Revision ID: 0014_contract_ext
Revises: 0013_insurance
Create Date: 2026-08-12
"""
from alembic import op

revision = "0014_contract_ext"
down_revision = "0013_insurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # —— 合同变更 ——
    op.execute("""
        CREATE TABLE contract_amendments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id UUID NOT NULL REFERENCES contracts(id),
            amendment_date DATE NOT NULL,
            change_type VARCHAR(30) NOT NULL,
            before_json JSONB,
            after_json JSONB,
            reason TEXT,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_ctramend_contract ON contract_amendments(contract_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_ctramend_updated BEFORE UPDATE ON contract_amendments FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 合同终止 ——
    op.execute("""
        CREATE TABLE contract_terminations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id UUID NOT NULL REFERENCES contracts(id),
            termination_date DATE NOT NULL,
            reason TEXT,
            settlement_note TEXT,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_ctrterm_contract ON contract_terminations(contract_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_ctrterm_updated BEFORE UPDATE ON contract_terminations FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 单据编号规则（SN 规则回迁：GPU-{yyyymm}-{seq5} 生成结果与一期硬编码一致） ——
    op.execute("""
        CREATE TABLE doc_number_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_type VARCHAR(50) NOT NULL,
            prefix VARCHAR(20) NOT NULL DEFAULT '',
            date_format VARCHAR(20),
            seq_digits INTEGER NOT NULL DEFAULT 5 CHECK (seq_digits BETWEEN 1 AND 10),
            current_period VARCHAR(20),
            last_seq INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_docnum_type ON doc_number_rules(doc_type) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_docnum_updated BEFORE UPDATE ON doc_number_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 金租规则参数表 ——
    op.execute("""
        CREATE TABLE leasing_rule_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_key VARCHAR(50) NOT NULL,
            rule_value VARCHAR(200) NOT NULL,
            description VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_leasing_rule_key ON leasing_rule_configs(rule_key) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_leasing_rule_updated BEFORE UPDATE ON leasing_rule_configs FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— devices +预付款累计已结转（D2：复用 devices 字段单源；nullable，NULL 按 0 计） ——
    op.execute("ALTER TABLE devices ADD COLUMN prepayment_settled_amount DECIMAL(18,2) CHECK (prepayment_settled_amount IS NULL OR prepayment_settled_amount >= 0)")

    # —— contracts 合同深化 +6 字段（全 nullable） ——
    op.execute("ALTER TABLE contracts ADD COLUMN purchase_type VARCHAR(20)")
    op.execute("ALTER TABLE contracts ADD COLUMN delivery_terms VARCHAR(200)")
    op.execute("ALTER TABLE contracts ADD COLUMN warranty_terms VARCHAR(200)")
    op.execute("ALTER TABLE contracts ADD COLUMN penalty_terms VARCHAR(200)")
    op.execute("ALTER TABLE contracts ADD COLUMN prepayment_ratio NUMERIC(10,8)")
    op.execute("ALTER TABLE contracts ADD COLUMN collection_account_type VARCHAR(20)")


def downgrade() -> None:
    """纯反序 DROP（0014 全 nullable 纯加法，真无损可逆）。"""
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS collection_account_type")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS prepayment_ratio")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS penalty_terms")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS warranty_terms")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS delivery_terms")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS purchase_type")
    op.execute("ALTER TABLE devices DROP COLUMN IF EXISTS prepayment_settled_amount")
    op.execute("DROP TRIGGER IF EXISTS trg_leasing_rule_updated ON leasing_rule_configs")
    op.execute("DROP TABLE IF EXISTS leasing_rule_configs")
    op.execute("DROP TRIGGER IF EXISTS trg_docnum_updated ON doc_number_rules")
    op.execute("DROP TABLE IF EXISTS doc_number_rules")
    op.execute("DROP TRIGGER IF EXISTS trg_ctrterm_updated ON contract_terminations")
    op.execute("DROP TABLE IF EXISTS contract_terminations")
    op.execute("DROP TRIGGER IF EXISTS trg_ctramend_updated ON contract_amendments")
    op.execute("DROP TABLE IF EXISTS contract_amendments")
