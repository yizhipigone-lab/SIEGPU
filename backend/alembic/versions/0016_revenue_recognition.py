"""收入确认管理 + 科目映射（三期 §4.2）：revenue_recognitions + gl_account_mappings。

纯加表 → 真·无损可逆。与 db/schema.sql 双写一致（test_migration_parity 守护）。
核心口径（父计划 §4.2）：billings=应收计费（含税，面向客户对账）；revenue_recognitions=权责收入
（不含税，面向核算）；与开票/收款解耦；billing_id 关联但不强制一一对应（可先确认后开票）。

Revision ID: 0016_revenue_recognition
Revises: 0015_payment_approval
Create Date: 2026-08-13
"""
from alembic import op

revision = "0016_revenue_recognition"
down_revision = "0015_payment_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # —— 收入确认：草稿（计费自动生成）→ 已确认（审批通过）→ 已同步EBS（Mock 凭证出站） ——
    op.execute("""
        CREATE TABLE revenue_recognitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            contract_id UUID NOT NULL REFERENCES contracts(id),
            batch_id UUID REFERENCES orders(id),
            device_id UUID REFERENCES devices(id),
            billing_id UUID REFERENCES billings(id),
            period_label VARCHAR(20) NOT NULL,
            recognition_date DATE NOT NULL,
            amount DECIMAL(18,2) NOT NULL CHECK (amount >= 0),   -- 不含税
            currency_code VARCHAR(10),
            booked_rate DECIMAL(18,8),
            revenue_method VARCHAR(20),                          -- 快照合同判定结果（W3-4）
            status VARCHAR(20) NOT NULL DEFAULT '草稿' CHECK (status IN ('草稿','已确认','已同步EBS')),
            approval_id UUID REFERENCES approvals(id),
            confirmed_by UUID REFERENCES users(id),
            confirmed_at TIMESTAMPTZ,
            voucher_json JSONB,                                  -- Mock 凭证（借贷科目+摘要）
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    # 同一 billing 只生成一张确认单（幂等；billing_id 可空故部分唯一）
    op.execute("CREATE UNIQUE INDEX uq_revrec_billing ON revenue_recognitions(billing_id) WHERE deleted_at IS NULL AND billing_id IS NOT NULL")
    op.execute("CREATE INDEX idx_revrec_project ON revenue_recognitions(project_id, status) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_revrec_device ON revenue_recognitions(device_id) WHERE deleted_at IS NULL AND device_id IS NOT NULL")
    op.execute("CREATE TRIGGER trg_revrec_updated BEFORE UPDATE ON revenue_recognitions FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 科目映射：业务事件(+核算路径) → EBS 借贷科目 ——
    op.execute("""
        CREATE TABLE gl_account_mappings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            business_event VARCHAR(50) NOT NULL,    -- 收入确认/折旧计提/付款/收款/汇兑损益/金租放款/利息计提…
            revenue_method VARCHAR(20),             -- NULL=通用
            debit_account VARCHAR(50) NOT NULL,
            credit_account VARCHAR(50) NOT NULL,
            description_template VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_glam_event_method ON gl_account_mappings(business_event, COALESCE(revenue_method, '')) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_glam_updated BEFORE UPDATE ON gl_account_mappings FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    """纯反序 DROP（0016 仅加表，真无损可逆）。"""
    op.execute("DROP TRIGGER IF EXISTS trg_glam_updated ON gl_account_mappings")
    op.execute("DROP TABLE IF EXISTS gl_account_mappings")
    op.execute("DROP TRIGGER IF EXISTS trg_revrec_updated ON revenue_recognitions")
    op.execute("DROP TABLE IF EXISTS revenue_recognitions")
