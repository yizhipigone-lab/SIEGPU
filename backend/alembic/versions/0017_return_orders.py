"""采购退货（三期 §4.4）：return_orders + return_order_devices + devices.status CHECK 扩'已退货'。

退货全链路（父计划 §4.4）：退货申请（单台/批量）→ 出库确认（设备置'已退货'）→ 供应商收货
（财务联动：已转固→资产减少+折旧冲回留痕；未转固→冲减在途物资）→ 红字发票
（invoices direction=PAYABLE + reversal_of_id）→ 退款登记（capital_transactions IN）→ 退款核销
（payment_settlements）。预付款追回额在退货单上落字段（已付预付款→追回口径）。
devices.status CHECK 扩 '已退货'（只扩不收窄，含全部旧 7 枚举；存量无'已退货'行，downgrade 直接回旧）。
与 db/schema.sql 双写一致（test_migration_parity 守护）。

Revision ID: 0017_return_orders
Revises: 0016_revenue_recognition
Create Date: 2026-08-13
"""
from alembic import op

revision = "0017_return_orders"
down_revision = "0016_revenue_recognition"
branch_labels = None
depends_on = None

_DEV_STATUS_OLD = "('订货','在途','到货','己方压测','上架','客户压测','点亮验收')"
_DEV_STATUS_NEW = "('订货','在途','到货','己方压测','上架','客户压测','点亮验收','已退货')"


def upgrade() -> None:
    # —— 退货单 ——
    op.execute("""
        CREATE TABLE return_orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            original_order_id UUID REFERENCES orders(id),
            original_invoice_id UUID REFERENCES invoices(id),   -- 原采购发票（红字发票挂 reversal_of_id）
            return_type VARCHAR(30) NOT NULL CHECK (return_type IN ('到货不合格','压测不通过','合同终止')),
            status VARCHAR(30) NOT NULL DEFAULT '退货申请' CHECK (status IN ('退货申请','已出库','供应商已收货','已开红字发票','已退款核销','预付款已冲回')),
            total_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),  -- Σ设备退货额（原值口径）
            prepayment_recover DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (prepayment_recover >= 0),  -- 预付款追回额
            reason TEXT,
            red_invoice_id UUID REFERENCES invoices(id),        -- 红字发票
            refund_txn_id UUID REFERENCES capital_transactions(id),  -- 退款流水
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_return_project ON return_orders(project_id, status) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_return_updated BEFORE UPDATE ON return_orders FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 退货单-设备（单台/批量；amount=单台退货额） ——
    op.execute("""
        CREATE TABLE return_order_devices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            return_order_id UUID NOT NULL REFERENCES return_orders(id),
            device_id UUID NOT NULL REFERENCES devices(id),
            amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (amount >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_return_device ON return_order_devices(return_order_id, device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_returndev_device ON return_order_devices(device_id) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_returndev_updated BEFORE UPDATE ON return_order_devices FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— devices.status CHECK 扩 '已退货'（只扩不收窄） ——
    op.execute("ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_status_check")
    op.execute(f"ALTER TABLE devices ADD CONSTRAINT devices_status_check CHECK (status IN {_DEV_STATUS_NEW})")


def downgrade() -> None:
    """0017：先清'已退货'设备行（guard：收窄 CHECK 前删除本迁移产物状态行）+ 回旧 CHECK + 反序 DROP。"""
    op.execute("DELETE FROM devices WHERE status = '已退货'")
    op.execute("ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_status_check")
    op.execute(f"ALTER TABLE devices ADD CONSTRAINT devices_status_check CHECK (status IN {_DEV_STATUS_OLD})")
    op.execute("DROP TRIGGER IF EXISTS trg_returndev_updated ON return_order_devices")
    op.execute("DROP TABLE IF EXISTS return_order_devices")
    op.execute("DROP TRIGGER IF EXISTS trg_return_updated ON return_orders")
    op.execute("DROP TABLE IF EXISTS return_orders")
