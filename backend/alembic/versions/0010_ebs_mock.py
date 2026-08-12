"""EBS 接口 Mock 骨架（二期 W1-2）：ebs_field_mappings + ebs_sync_logs。

纯加表（字段映射配置 + 同步日志），不动任何现有表 → 真·无损可逆。
手写 op.execute 裸 SQL（autogenerate 因 fk_inv_billing 的 DEFERRED 漂移不可用，见 0009 说明；
手写可避免把历史漂移卷进新迁移）。
与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，test_migration_parity 守护）。
Mock 阶段仅 SIEGPU→EBS 出站；EBS→SIEGPU 入站属期外里程碑（父计划 §0.3）。

direction 用 SIEGPU_TO_EBS / EBS_TO_SIEGPU（箭头 → 是非 ASCII，入库改 ASCII 枚举串更稳）。

Revision ID: 0010_ebs_mock
Revises: 0009_notifications
Create Date: 2026-08-10
"""
from alembic import op

revision = "0010_ebs_mock"
down_revision = "0009_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # —— 字段映射配置：SIEGPU 字段 ↔ EBS 字段 + 转换规则 ——
    op.execute("""
        CREATE TABLE ebs_field_mappings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type VARCHAR(40) NOT NULL,
            siegpu_field VARCHAR(100) NOT NULL,
            ebs_field VARCHAR(100) NOT NULL,
            transform_rule VARCHAR(50) NOT NULL DEFAULT 'direct',
            transform_config JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    # 同实体+同字段唯一（防重复映射），按 entity_type 拉整套映射
    op.execute("CREATE UNIQUE INDEX idx_ebs_fm_entity_field ON ebs_field_mappings(entity_type, siegpu_field) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX idx_ebs_fm_entity ON ebs_field_mappings(entity_type) WHERE deleted_at IS NULL")
    op.execute("CREATE TRIGGER trg_ebs_fm_updated BEFORE UPDATE ON ebs_field_mappings FOR EACH ROW EXECUTE FUNCTION set_updated_at()")

    # —— 同步日志：每次出站一行，entity_version 内容 hash 做幂等/乱序判定 ——
    op.execute("""
        CREATE TABLE ebs_sync_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type VARCHAR(40) NOT NULL,
            entity_id VARCHAR(64) NOT NULL,
            entity_version VARCHAR(64) NOT NULL,
            direction VARCHAR(20) NOT NULL DEFAULT 'SIEGPU_TO_EBS',
            sync_type VARCHAR(16) NOT NULL,
            status VARCHAR(20) NOT NULL,
            ebs_reference VARCHAR(64),
            request_payload JSONB,
            response_payload JSONB,
            error_message VARCHAR(500),
            retry_count INTEGER NOT NULL DEFAULT 0,
            synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
    """)
    # 幂等查重：同实体同版本已成功 → 跳过（不新建 log）
    op.execute("CREATE INDEX idx_ebs_sl_entity_version ON ebs_sync_logs(entity_type, entity_id, entity_version)")
    # 监控页查询：按实体/状态/时间倒序
    op.execute("CREATE INDEX idx_ebs_sl_entity_status ON ebs_sync_logs(entity_type, status, synced_at DESC)")
    # 失败重试：捞 status=FAILED 的行
    op.execute("CREATE INDEX idx_ebs_sl_retry ON ebs_sync_logs(status, retry_count) WHERE status = 'FAILED'")
    op.execute("CREATE TRIGGER trg_ebs_sl_updated BEFORE UPDATE ON ebs_sync_logs FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    """纯反序 DROP（0010 仅加表，真无损可逆）。"""
    op.execute("DROP TRIGGER IF EXISTS trg_ebs_sl_updated ON ebs_sync_logs")
    op.execute("DROP INDEX IF EXISTS idx_ebs_sl_retry")
    op.execute("DROP INDEX IF EXISTS idx_ebs_sl_entity_status")
    op.execute("DROP INDEX IF EXISTS idx_ebs_sl_entity_version")
    op.execute("DROP TABLE IF EXISTS ebs_sync_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_ebs_fm_updated ON ebs_field_mappings")
    op.execute("DROP INDEX IF EXISTS idx_ebs_fm_entity")
    op.execute("DROP INDEX IF EXISTS idx_ebs_fm_entity_field")
    op.execute("DROP TABLE IF EXISTS ebs_field_mappings")
