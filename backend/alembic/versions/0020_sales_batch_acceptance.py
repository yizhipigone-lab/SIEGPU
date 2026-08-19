"""销售分批次验收（W4）：sales_orders 加批次字段 + sales_batch_devices 表 + acceptance_records.shelve。

Revision ID: 0020_sales_batch_acceptance
Revises: 0019_disbursement_acceptance
Create Date: 2026-08-19
"""
from alembic import op

revision = "0020_sales_batch_acceptance"
down_revision = "0019_disbursement_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 销售订单复用为「销售批次」载体
    op.execute("ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS is_batch BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS batch_name VARCHAR(100)")
    op.execute("ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS batch_status VARCHAR(20)")

    # 2) 销售批次-设备组合关系表
    op.execute("""
        CREATE TABLE IF NOT EXISTS sales_batch_devices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sales_batch_id UUID NOT NULL REFERENCES sales_orders(id),
            device_id UUID NOT NULL REFERENCES devices(id),
            action VARCHAR(10) NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            operated_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_sales_batch_devices_updated') THEN
                CREATE TRIGGER trg_sales_batch_devices_updated BEFORE UPDATE ON sales_batch_devices
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sbd_batch ON sales_batch_devices(sales_batch_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sbd_device ON sales_batch_devices(device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_sbd_active_device ON sales_batch_devices(device_id) WHERE active AND deleted_at IS NULL")

    # 3) 验收记录：销售验收勾选「上架」→ 审批通过同步标记上架完成
    op.execute("ALTER TABLE acceptance_records ADD COLUMN IF NOT EXISTS shelve BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE acceptance_records DROP COLUMN IF EXISTS shelve")
    op.execute("DROP INDEX IF EXISTS uq_sbd_active_device")
    op.execute("DROP INDEX IF EXISTS idx_sbd_device")
    op.execute("DROP INDEX IF EXISTS idx_sbd_batch")
    op.execute("DROP TABLE IF EXISTS sales_batch_devices")
    op.execute("ALTER TABLE sales_orders DROP COLUMN IF EXISTS batch_status")
    op.execute("ALTER TABLE sales_orders DROP COLUMN IF EXISTS batch_name")
    op.execute("ALTER TABLE sales_orders DROP COLUMN IF EXISTS is_batch")
