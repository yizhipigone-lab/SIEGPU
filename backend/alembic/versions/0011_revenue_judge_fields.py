"""收入核算路径判定（二期 W3-4）：contracts +7 字段（全 nullable，纯加法）。

输入 3 字段（pricing_authority/inventory_risk_bearer/principal_role）+ 判定结果快照
（revenue_method/method_judge_basis）+ 人工确认留痕（method_confirmed_by/at）。
不加 NOT NULL、不改旧列 → 真·无损可逆（downgrade 直接 DROP COLUMN）。
与 db/schema.sql 双写一致（conftest 由 schema.sql 建表，test_migration_parity 守护）。

Revision ID: 0011_revenue_judge_fields
Revises: 0010_ebs_mock
Create Date: 2026-08-12
"""
from alembic import op

revision = "0011_revenue_judge_fields"
down_revision = "0010_ebs_mock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 判定输入（定价权 / 存货风险承担方 / 主要责任人-代理人）
    op.execute("ALTER TABLE contracts ADD COLUMN pricing_authority VARCHAR(20) CHECK (pricing_authority IS NULL OR pricing_authority IN ('自主定价','客户定价','上游定价'))")
    op.execute("ALTER TABLE contracts ADD COLUMN inventory_risk_bearer VARCHAR(20) CHECK (inventory_risk_bearer IS NULL OR inventory_risk_bearer IN ('我方','客户','上游'))")
    op.execute("ALTER TABLE contracts ADD COLUMN principal_role VARCHAR(20) CHECK (principal_role IS NULL OR principal_role IN ('主要责任人','代理人'))")
    # 判定结果快照（系统判定 + 人工确认；revenue_method 含 R4 兜底「待判定」）
    op.execute("ALTER TABLE contracts ADD COLUMN revenue_method VARCHAR(20) CHECK (revenue_method IS NULL OR revenue_method IN ('总额法','净额法','经营租赁','服务费','待判定'))")
    op.execute("ALTER TABLE contracts ADD COLUMN method_judge_basis TEXT")
    # 人工确认留痕
    op.execute("ALTER TABLE contracts ADD COLUMN method_confirmed_by UUID REFERENCES users(id)")
    op.execute("ALTER TABLE contracts ADD COLUMN method_confirmed_at TIMESTAMPTZ")

    # audit CHECK 扩 2 个新动作（只扩不收窄，含全部旧 18 枚举；约束名 audit_logs_action_check 沿用 0008 确认）
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute("""ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check
        CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE',
                          'ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD',
                          'DISBURSE','CAPITAL_TXN','LIGHT_ON','ALLOCATE','ALLOCATE_RETURN','LEASEBACK_SALE',
                          'REVENUE_JUDGE','REVENUE_OVERRIDE'))""")


def downgrade() -> None:
    """纯 DROP COLUMN + audit CHECK 回旧 18 枚举（0011 无数据迁移，真无损可逆）。"""
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS method_confirmed_at")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS method_confirmed_by")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS method_judge_basis")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS revenue_method")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS principal_role")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS inventory_risk_bearer")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS pricing_authority")
    # audit CHECK 回旧 18 枚举：先清 0011 新动作行（同 0007 DELETE guard 范式——回滚即撤销本迁移产物，
    # 否则存量 REVENUE_* 行会让收窄的 CHECK ADD 直接失败），再 DROP/ADD 回旧约束
    op.execute("DELETE FROM audit_logs WHERE action IN ('REVENUE_JUDGE','REVENUE_OVERRIDE')")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check")
    op.execute("""ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_action_check
        CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE',
                          'ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD',
                          'DISBURSE','CAPITAL_TXN','LIGHT_ON','ALLOCATE','ALLOCATE_RETURN','LEASEBACK_SALE'))""")
