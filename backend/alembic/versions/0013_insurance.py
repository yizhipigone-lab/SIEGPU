"""保险管理（二期 W7-8）：insurance_policies + insurance_policy_devices + insurance_configs。

纯加表，不动现有表 → 真·无损可逆。与 db/schema.sql 双写一致（test_migration_parity 守护）。
硬约束（保费归集窗口）在 service 层校验：仅点亮前可进资产原值，点亮后一律长期待摊。

Revision ID: 0013_insurance
Revises: 0012_currency_exchange
Create Date: 2026-08-12
"""
from alembic import op

revision = "0013_insurance"
down_revision = "0012_currency_exchange"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # —— 保单主表 ——
    op.execute("""
        CREATE TABLE insurance_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            batch_id UUID REFERENCES orders(id),
            policy_type VARCHAR(20) NOT NULL CHECK (policy_type IN ('运输险','财产险')),
            policy_no VARCHAR(100),
            insurer_id UUID REFERENCES suppliers(id),
            insured_amount DECIMAL(18,2) CHECK (insured_amount IS NULL OR insured_amount >= 0),
            premium_rate NUMERIC(10,8) CHECK (premium_rate IS NULL OR premium_rate >= 0),
            premium_amount DECIMAL(18,2) CHECK (premium_amount IS NULL OR premium_amount >= 0),
            start_date DATE,
            end_date DATE,
            status VARCHAR(20) NOT NULL DEFAULT '待确认' CHECK (status IN ('待确认','已生效','理赔中','已到期','已退保')),
            trigger_event VARCHAR(20),
            cost_allocation VARCHAR(20) CHECK (cost_allocation IS NULL OR cost_allocation IN ('资产原值','长期待摊')),
            amortization_months INTEGER CHECK (amortization_months IS NULL OR amortization_months > 0),
            collected_at TIMESTAMPTZ,
            claims JSONB,
            file_path VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_inspol_project ON insurance_policies(project_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_inspol_batch ON insurance_policies(batch_id) WHERE deleted_at IS NULL AND batch_id IS NOT NULL")
    op.execute("CREATE INDEX idx_inspol_status ON insurance_policies(status, end_date) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_inspol_updated BEFORE UPDATE ON insurance_policies FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 保单-设备分摊（价值占比，末台吃尾差） ——
    op.execute("""
        CREATE TABLE insurance_policy_devices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            policy_id UUID NOT NULL REFERENCES insurance_policies(id),
            device_id UUID NOT NULL REFERENCES devices(id),
            allocated_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (allocated_amount >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_inspd_policy_device ON insurance_policy_devices(policy_id, device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_inspd_device ON insurance_policy_devices(device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_inspd_updated BEFORE UPDATE ON insurance_policy_devices FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 投保配置 ——
    op.execute("""
        CREATE TABLE insurance_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            policy_type VARCHAR(20) NOT NULL CHECK (policy_type IN ('运输险','财产险')),
            default_rate NUMERIC(10,8) CHECK (default_rate IS NULL OR default_rate >= 0),
            insured_ratio NUMERIC(10,8) CHECK (insured_ratio IS NULL OR insured_ratio >= 0),
            insurer_id UUID REFERENCES suppliers(id),
            cost_allocation VARCHAR(20) CHECK (cost_allocation IS NULL OR cost_allocation IN ('资产原值','长期待摊')),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_inscfg_type ON insurance_configs(policy_type) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_inscfg_updated BEFORE UPDATE ON insurance_configs FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    """纯反序 DROP（0013 仅加表，真无损可逆）。"""
    op.execute("DROP TRIGGER IF EXISTS trg_inscfg_updated ON insurance_configs")
    op.execute("DROP TABLE IF EXISTS insurance_configs")
    op.execute("DROP TRIGGER IF EXISTS trg_inspd_updated ON insurance_policy_devices")
    op.execute("DROP TABLE IF EXISTS insurance_policy_devices")
    op.execute("DROP TRIGGER IF EXISTS trg_inspol_updated ON insurance_policies")
    op.execute("DROP TABLE IF EXISTS insurance_policies")
