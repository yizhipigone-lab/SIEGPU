"""付款三重管控 + 通用审批 + 进项税（二期 W11-12）：3 新表 + invoices 进项字段。

新表：approvals（通用审批，单级落地多级留 level 扩展）/ payment_requests（付款申请→审批→登记→付款）
      / payment_settlements（多对多核销核心：一笔付款核销多发票/多批次/多台设备按金额逐台多行）。
加列：invoices +certification_status + certification_date（进项侧，审计 A10）。
全 nullable/纯加表 → 真·无损可逆。与 db/schema.sql 双写一致（test_migration_parity 守护）。

Revision ID: 0015_payment_approval
Revises: 0014_contract_ext
Create Date: 2026-08-13
"""
from alembic import op

revision = "0015_payment_approval"
down_revision = "0014_contract_ext"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # —— 通用审批（单级落地；level/max_level 留多级扩展） ——
    op.execute("""
        CREATE TABLE approvals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            biz_type VARCHAR(30) NOT NULL,          -- 项目立项/付款申请/预付款/预算调整/监管划转/合同变更/收入确认…
            biz_id UUID,                            -- 业务单据 id（payment_requests.id 等）
            title VARCHAR(200) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT '待审批' CHECK (status IN ('待审批','已通过','已驳回')),
            level INTEGER NOT NULL DEFAULT 1,       -- 当前级（本期单级恒 1）
            max_level INTEGER NOT NULL DEFAULT 1,   -- 多级扩展位
            submitted_by UUID REFERENCES users(id),
            approved_by UUID REFERENCES users(id),
            approved_at TIMESTAMPTZ,
            reject_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_approvals_biz ON approvals(biz_type, biz_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_approvals_status ON approvals(status) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_approvals_updated BEFORE UPDATE ON approvals FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 付款申请（三重管控：申请 → 审批 → 登记/付款） ——
    op.execute("""
        CREATE TABLE payment_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            contract_id UUID REFERENCES contracts(id),
            direction VARCHAR(4) NOT NULL DEFAULT 'OUT' CHECK (direction IN ('IN','OUT')),
            amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
            currency_code VARCHAR(10),
            reason TEXT,
            prepayment_offset DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (prepayment_offset >= 0),  -- 预付款冲抵额
            status VARCHAR(20) NOT NULL DEFAULT '待审批' CHECK (status IN ('待审批','已批准','已驳回','已付款')),
            approval_id UUID REFERENCES approvals(id),
            capital_transaction_id UUID REFERENCES capital_transactions(id),
            requested_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_payreq_project ON payment_requests(project_id, status) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_payreq_updated BEFORE UPDATE ON payment_requests FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 核销（多对多核心）：一笔流水 ↔ 多发票/多批次/多台设备（按金额逐台多行）；收款复用同表 ——
    op.execute("""
        CREATE TABLE payment_settlements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            capital_transaction_id UUID NOT NULL REFERENCES capital_transactions(id),
            invoice_id UUID REFERENCES invoices(id),      -- 可空：待认领/预付款冲抵
            batch_id UUID REFERENCES orders(id),          -- 可空
            device_id UUID REFERENCES devices(id),        -- 可空：按金额占比逐台多行
            amount DECIMAL(18,2) NOT NULL CHECK (amount >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_payset_txn ON payment_settlements(capital_transaction_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_payset_invoice ON payment_settlements(invoice_id) WHERE deleted_at IS NULL AND invoice_id IS NOT NULL")
    op.execute("CREATE INDEX idx_payset_device ON payment_settlements(device_id) WHERE deleted_at IS NULL AND device_id IS NOT NULL")
    op.execute("CREATE TRIGGER trg_payset_updated BEFORE UPDATE ON payment_settlements FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 进项侧（审计 A10）：认证/抵扣状态 ——
    op.execute("ALTER TABLE invoices ADD COLUMN certification_status VARCHAR(20) CHECK (certification_status IS NULL OR certification_status IN ('未认证','已认证','已抵扣'))")
    op.execute("ALTER TABLE invoices ADD COLUMN certification_date DATE")


def downgrade() -> None:
    """纯反序 DROP（0015 纯加表 + nullable 加列，真无损可逆）。"""
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS certification_date")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS certification_status")
    op.execute("DROP TRIGGER IF EXISTS trg_payset_updated ON payment_settlements")
    op.execute("DROP TABLE IF EXISTS payment_settlements")
    op.execute("DROP TRIGGER IF EXISTS trg_payreq_updated ON payment_requests")
    op.execute("DROP TABLE IF EXISTS payment_requests")
    op.execute("DROP TRIGGER IF EXISTS trg_approvals_updated ON approvals")
    op.execute("DROP TABLE IF EXISTS approvals")
