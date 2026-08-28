"""0028 S3：预付款台账表 prepayments + devices.prepayment_date（缺陷#5/#6，D2 裁定翻盘）。

- 新建 prepayments 表（payment_date/supplier_id/contract_id/amount/settled_amount/幂等键）
- devices + prepayment_date（可空=待补）
- 纯加法、无数据迁移：downgrade 反序 DROP 全部新对象，无损可逆。
"""
from alembic import op

revision = "0028_prepayments"
down_revision = "0027_assistant_writes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE prepayments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    supplier_id UUID REFERENCES suppliers(id),
    contract_id UUID REFERENCES contracts(id),
    device_id UUID REFERENCES devices(id),
    payment_date DATE,
    amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
    settled_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (settled_amount >= 0),
    idempotency_key VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_prepay_idem ON prepayments(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_prepay_project ON prepayments(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_prepay_device ON prepayments(device_id) WHERE deleted_at IS NULL AND device_id IS NOT NULL;
CREATE TRIGGER trg_prepayments_updated BEFORE UPDATE ON prepayments FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
    op.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS prepayment_date DATE;")


def downgrade():
    op.execute("ALTER TABLE devices DROP COLUMN IF EXISTS prepayment_date;")
    op.execute("DROP TABLE IF EXISTS prepayments;")
