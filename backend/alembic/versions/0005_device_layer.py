"""设备实体层（一期 W1-2）— 新增 devices/batch_devices/off_balance_registers 3 表 + 7 张现有表字段扩展。

与 db/schema.sql 保持一致（索引由 schema 手动维护，迁移同步创建）。

Revision ID: 0005_device_layer
Revises: 0004_audit
Create Date: 2026-08-04
"""
from alembic import op

revision = "0005_device_layer"
down_revision = "0004_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- 现有表字段扩展（全部 additive，带默认值） ----------
    op.execute("ALTER TABLE projects ADD COLUMN business_type VARCHAR(20) CHECK (business_type IS NULL OR business_type IN ('经营租赁','转售','自营'))")
    op.execute("ALTER TABLE projects ADD COLUMN leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租'))")
    op.execute("ALTER TABLE projects ADD COLUMN parent_id UUID REFERENCES projects(id)")
    op.execute("ALTER TABLE projects ADD COLUMN financing_plan JSONB")
    # status 枚举补"筹备中"
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_status_check")
    op.execute("ALTER TABLE projects ADD CONSTRAINT projects_status_check CHECK (status IN ('筹备中','进行中','暂停','已完成','已终止'))")

    op.execute("ALTER TABLE equipment_models ADD COLUMN resource_attr VARCHAR(20) CHECK (resource_attr IS NULL OR resource_attr IN ('自购资产','金租资产','转售资源'))")
    op.execute("ALTER TABLE equipment_models ADD COLUMN billing_modes JSONB")

    op.execute("ALTER TABLE suppliers ADD COLUMN is_leasing_org BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE suppliers ADD COLUMN leasing_coop_modes JSONB")

    op.execute("ALTER TABLE orders ADD COLUMN is_batch BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE orders ADD COLUMN batch_name VARCHAR(100)")
    op.execute("ALTER TABLE orders ADD COLUMN batch_status VARCHAR(20)")
    op.execute("ALTER TABLE orders ADD COLUMN flow_type VARCHAR(20) CHECK (flow_type IS NULL OR flow_type IN ('batch','device','transfer-resale'))")

    op.execute("ALTER TABLE contracts ADD COLUMN leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租'))")

    op.execute("ALTER TABLE leasing_processes ADD COLUMN leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租'))")
    op.execute("ALTER TABLE leasing_processes ADD COLUMN financing_type VARCHAR(30) CHECK (financing_type IS NULL OR financing_type IN ('金租直租','金租回租','银行流贷','项目贷款'))")
    op.execute("ALTER TABLE leasing_processes ADD COLUMN materials JSONB")

    # ---------- 新增表 ----------
    op.execute("""
        CREATE TABLE devices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sn VARCHAR(50) NOT NULL UNIQUE,
            project_id UUID NOT NULL REFERENCES projects(id),
            order_id UUID REFERENCES orders(id),
            batch_id UUID REFERENCES orders(id),
            sales_contract_id UUID REFERENCES contracts(id),
            equipment_model_id UUID NOT NULL REFERENCES equipment_models(id),
            supplier_id UUID REFERENCES suppliers(id),
            monthly_price DECIMAL(18,2) CHECK (monthly_price IS NULL OR monthly_price >= 0),
            config JSONB,
            leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租')),
            purchase_value DECIMAL(18,2) CHECK (purchase_value IS NULL OR purchase_value >= 0),
            prepayment_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (prepayment_amount >= 0),
            status VARCHAR(20) NOT NULL DEFAULT '订货' CHECK (status IN ('订货','在途','到货','己方压测','上架','客户压测','点亮验收')),
            ownership VARCHAR(20) CHECK (ownership IS NULL OR ownership IN ('表内自有','金租表外','转售表外')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_devices_project ON devices(project_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_devices_batch ON devices(batch_id) WHERE deleted_at IS NULL AND batch_id IS NOT NULL")
    op.execute("CREATE INDEX idx_devices_status ON devices(status) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_devices_updated BEFORE UPDATE ON devices FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    op.execute("""
        CREATE TABLE batch_devices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES orders(id),
            device_id UUID NOT NULL REFERENCES devices(id),
            action VARCHAR(10) NOT NULL CHECK (action IN ('加入','移出')),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            operated_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_batch_devices_active ON batch_devices(device_id) WHERE active AND deleted_at IS NULL")
    op.execute("CREATE INDEX idx_bd_batch ON batch_devices(batch_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_bd_updated BEFORE UPDATE ON batch_devices FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    op.execute("""
        CREATE TABLE off_balance_registers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id UUID NOT NULL REFERENCES devices(id),
            register_type VARCHAR(20) NOT NULL CHECK (register_type IN ('金租直租','售后回租','转售')),
            leasing_process_id UUID REFERENCES leasing_processes(id),
            start_date DATE,
            end_date DATE,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_obr_device ON off_balance_registers(device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_obr_updated BEFORE UPDATE ON off_balance_registers FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # billings 按台计费（依赖 devices 已建）
    op.execute("ALTER TABLE billings ADD COLUMN device_id UUID REFERENCES devices(id)")
    op.execute("CREATE INDEX idx_billing_device ON billings(device_id) WHERE deleted_at IS NULL AND device_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_billing_device")
    op.execute("ALTER TABLE billings DROP COLUMN IF EXISTS device_id")

    op.execute("DROP TABLE IF EXISTS off_balance_registers")
    op.execute("DROP TABLE IF EXISTS batch_devices")
    op.execute("DROP TABLE IF EXISTS devices")

    op.execute("ALTER TABLE leasing_processes DROP COLUMN IF EXISTS materials")
    op.execute("ALTER TABLE leasing_processes DROP COLUMN IF EXISTS financing_type")
    op.execute("ALTER TABLE leasing_processes DROP COLUMN IF EXISTS leasing_mode")

    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS leasing_mode")

    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS flow_type")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS batch_status")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS batch_name")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS is_batch")

    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS leasing_coop_modes")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS is_leasing_org")

    op.execute("ALTER TABLE equipment_models DROP COLUMN IF EXISTS billing_modes")
    op.execute("ALTER TABLE equipment_models DROP COLUMN IF EXISTS resource_attr")

    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_status_check")
    op.execute("ALTER TABLE projects ADD CONSTRAINT projects_status_check CHECK (status IN ('进行中','暂停','已完成','已终止'))")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS financing_plan")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS parent_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS leasing_mode")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS business_type")
