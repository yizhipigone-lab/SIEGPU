"""assets 一机一卡 + operation_status + 转固/运营分离；billings 唯一索引迁 device 维度（一期 W5-6）。

- assets：+device_id（一机一卡部分唯一）、+operation_status（已转固未运营/运营中/已处置）；
  start_date/end_date/4 折旧字段放宽 nullable（上架建卡时不折旧，点亮验收起折旧）。
- billings：uq_billing_period 索引从 (sales_order_id, period_index) 迁到 (device_id, period_index)
  （H-1 漂移修复；旧 service 从不写 sales_order_id，旧索引实际未挡重复，迁走零破坏）。
- 历史批量资产卡拆分（D6）见 upgrade 末尾 split_bulk_assets_to_per_device 调用。

与 db/schema.sql 保持一致（conftest 由 schema.sql 建表，迁移供 dev/prod；一致性由 test_migration_parity 守护）。

Revision ID: 0007_asset_per_device
Revises: 0006_device_stages
Create Date: 2026-08-07
"""
from alembic import op

revision = "0007_asset_per_device"
down_revision = "0006_device_stages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- assets：+device_id +operation_status，放宽 6 字段 NOT NULL ----------
    op.execute("""
        ALTER TABLE assets
            ADD COLUMN device_id UUID REFERENCES devices(id),
            ADD COLUMN operation_status VARCHAR(20) NOT NULL DEFAULT '已转固未运营'
                CHECK (operation_status IN ('已转固未运营','运营中','已处置'))
    """)
    # 存量资产全部已起折旧 → 回填运营中（W5-6 前所有资产都走 light_on 即起折旧）
    op.execute("UPDATE assets SET operation_status='运营中' WHERE deleted_at IS NULL")
    # 放宽 NOT NULL（CHECK >=0 对 NULL 自动通过，约束保留）；逐列写出便于 parity 静态校验
    op.execute("ALTER TABLE assets ALTER COLUMN start_date DROP NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN end_date DROP NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN residual_value DROP NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN depreciable_value DROP NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN annual_depreciation DROP NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN monthly_depreciation DROP NOT NULL")
    # 一机一卡：device_id 部分唯一（legacy order 维资产 device_id=NULL 不被挡）
    op.execute("""
        CREATE UNIQUE INDEX uq_assets_device ON assets(device_id)
        WHERE deleted_at IS NULL AND device_id IS NOT NULL
    """)

    # ---------- billings：H-1 索引迁 device 维度 ----------
    op.execute("DROP INDEX IF EXISTS uq_billing_period")
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_period ON billings(device_id, period_index)
        WHERE deleted_at IS NULL AND device_id IS NOT NULL
    """)

    # ---------- 历史批量卡拆分（D6；空库跳过，Σ 不变量失败即整体回滚） ----------
    from app.utils.data_migration import split_bulk_assets_to_per_device
    split_bulk_assets_to_per_device(op.get_bind())


def downgrade() -> None:
    """NOTE：历史批量卡拆分不可无损回滚（拆出的 devices/assets 可能已被 W5-6 计费/折旧引用）。
    downgrade 仅做 DDL 反序 + 清理 W5-6 引入的未运营卡；生产回滚需 DBA 介入。
    """
    # billings 索引回旧维度
    op.execute("DROP INDEX IF EXISTS uq_billing_period")
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_period ON billings(sales_order_id, period_index)
        WHERE deleted_at IS NULL AND sales_order_id IS NOT NULL
    """)

    # assets：回 NOT NULL 前先删 W5-6 引入的 NULL 折旧行（未运营卡 / 拆分单台卡若被软删已不计）
    op.execute("""
        DELETE FROM assets
        WHERE start_date IS NULL OR end_date IS NULL OR residual_value IS NULL
           OR depreciable_value IS NULL OR annual_depreciation IS NULL
           OR monthly_depreciation IS NULL
    """)
    op.execute("ALTER TABLE assets ALTER COLUMN monthly_depreciation SET NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN annual_depreciation SET NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN depreciable_value SET NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN residual_value SET NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN end_date SET NOT NULL")
    op.execute("ALTER TABLE assets ALTER COLUMN start_date SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS uq_assets_device")
    op.execute("ALTER TABLE assets DROP COLUMN IF EXISTS operation_status")
    op.execute("ALTER TABLE assets DROP COLUMN IF EXISTS device_id")
