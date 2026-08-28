"""0032 缺陷修复批（2026-08-28 测试问题登记表）。

- #7：contracts.purchase_biz_type 列（设备采购/服务采购/金租融资，独立 CHECK）
- #8：contract_line_items 合同明细行表（行级税率，多税率录入）
- #16：存量设备状态重算（新派生逻辑：跳过未开始节点，修复卡"订货"）+
      存量设备补"订货已完成"节点行（有节点行但订货未开始的设备）
"""
from alembic import op

revision = "0032_issue_fix_batch"
down_revision = "0031_lease_void"
branch_labels = None
depends_on = None


def upgrade():
    # #7 采购侧业务类型（纯加法，NULL 不受约束）
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS purchase_biz_type VARCHAR(20);")
    op.execute("""
        ALTER TABLE contracts DROP CONSTRAINT IF EXISTS contracts_purchase_biz_type_check;
        ALTER TABLE contracts ADD CONSTRAINT contracts_purchase_biz_type_check
            CHECK (purchase_biz_type IS NULL OR purchase_biz_type IN ('设备采购','服务采购','金租融资'));
    """)

    # #8 合同明细行表
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_line_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            contract_id UUID NOT NULL REFERENCES contracts(id),
            seq INTEGER NOT NULL,
            name VARCHAR(200) NOT NULL,
            qty NUMERIC(18,4) NOT NULL DEFAULT 1,
            unit_price NUMERIC(18,2) NOT NULL,
            tax_rate NUMERIC(10,8) NOT NULL DEFAULT 0.13,
            line_amount NUMERIC(18,2) NOT NULL,
            line_tax NUMERIC(18,2) NOT NULL,
            line_amount_incl NUMERIC(18,2) NOT NULL,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_contract_line_items_contract_id ON contract_line_items(contract_id);
    """)

    # #16 存量数据修复：
    # a) 有节点行但订货未开始的设备 → 订货补为已完成（建档即已订货）
    op.execute("""
        UPDATE device_stages ds SET status = '已完成'
        WHERE ds.stage = '订货' AND ds.status = '未开始'
          AND EXISTS (SELECT 1 FROM device_stages ds2
                      WHERE ds2.device_id = ds.device_id AND ds2.seq > 1
                        AND ds2.status IN ('已完成','进行中','不合格'));
    """)
    # a2) 滞留"进行中"的前序节点（后序节点已有完成）→ 补为已完成。
    #     这正是缺陷#16 的存量病灶：到货停在"进行中"，后面己方压测/上架/点亮全完成，
    #     旧派生逻辑永远返回"到货"。
    op.execute("""
        UPDATE device_stages ds SET status = '已完成'
        WHERE ds.status = '进行中'
          AND EXISTS (SELECT 1 FROM device_stages ds2
                      WHERE ds2.device_id = ds.device_id AND ds2.seq > ds.seq
                        AND ds2.status = '已完成');
    """)
    # b) 按新派生逻辑重算全部设备 status（跳过未开始节点）
    op.execute("""
        UPDATE devices d SET status = sub.new_status
        FROM (
            SELECT dev.id,
                   COALESCE((
                       SELECT s.stage FROM device_stages s
                       WHERE s.device_id = dev.id
                         AND s.status IN ('进行中','不合格')
                       ORDER BY s.seq LIMIT 1
                   ), (
                       SELECT s2.stage FROM device_stages s2
                       WHERE s2.device_id = dev.id AND s2.status = '未开始'
                       ORDER BY s2.seq LIMIT 1
                   ), '点亮验收') AS new_status
            FROM devices dev
            WHERE dev.status <> '已退货'
        ) sub
        WHERE d.id = sub.id AND d.status <> '已退货';
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS contract_line_items;")
    op.execute("ALTER TABLE contracts DROP CONSTRAINT IF EXISTS contracts_purchase_biz_type_check;")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS purchase_biz_type;")
