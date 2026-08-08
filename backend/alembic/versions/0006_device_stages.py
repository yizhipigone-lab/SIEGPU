"""设备节点状态表 device_stages + orders 批次行 NOT NULL 放宽（一期 W3-4）。

- 新增 device_stages 表（设备粒度 7 节点状态，懒初始化）
- orders 的 equipment_model_id/quantity/unit_price/total_amount 放宽为可空（批次行跨型号组合，审计 A4）

与 db/schema.sql 保持一致（conftest 由 schema.sql 建表，迁移供 dev/prod；一致性由 test_migration_parity 守护）。

Revision ID: 0006_device_stages
Revises: 0005_device_layer
Create Date: 2026-08-06
"""
from alembic import op

revision = "0006_device_stages"
down_revision = "0005_device_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- 新增 device_stages 表 ----------
    op.execute("""
        CREATE TABLE device_stages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id UUID NOT NULL REFERENCES devices(id),
            stage VARCHAR(20) NOT NULL CHECK (stage IN ('订货','在途','到货','己方压测','上架','客户压测','点亮验收')),
            seq INTEGER NOT NULL CHECK (seq BETWEEN 1 AND 7),
            status VARCHAR(20) NOT NULL DEFAULT '未开始' CHECK (status IN ('未开始','进行中','已完成','不合格')),
            planned_date DATE,
            actual_date DATE,
            attachment_path VARCHAR(500),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_device_stages_device ON device_stages(device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_device_stages_updated BEFORE UPDATE ON device_stages FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # ---------- orders 批次行 NOT NULL 放宽（CHECK 保留，PG 下 NULL 过 CHECK） ----------
    op.execute("ALTER TABLE orders ALTER COLUMN equipment_model_id DROP NOT NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN quantity DROP NOT NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN unit_price DROP NOT NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN total_amount DROP NOT NULL")


def downgrade() -> None:
    # 恢复 NOT NULL 前，必须先清理 W3-4 引入的 NULL 批次行（这些行在 W3-4 前的 schema 下本就不存在）。
    # 仅删除 4 列任一为空的批次行，避免回填错值（批次汇总值由设备聚合派生，不可手填）。
    op.execute("""
        DELETE FROM orders
        WHERE equipment_model_id IS NULL OR quantity IS NULL
           OR unit_price IS NULL OR total_amount IS NULL
    """)
    op.execute("ALTER TABLE orders ALTER COLUMN total_amount SET NOT NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN unit_price SET NOT NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN quantity SET NOT NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN equipment_model_id SET NOT NULL")

    op.execute("DROP INDEX IF EXISTS idx_device_stages_device")
    op.execute("DROP TABLE IF EXISTS device_stages")
