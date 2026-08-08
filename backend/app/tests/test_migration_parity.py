"""schema.sql ↔ alembic 双写一致性（审计 Defect F）。

conftest 从 schema.sql 建表（不跑 alembic），故每处 schema 改动必须 schema.sql + alembic 双写。
此测试静态断言两处同时含 device_stages 表 DDL + orders 批次行 NOT NULL 放宽，防漂移。
"""
from pathlib import Path

# backend/app/tests/ → parents[2] = backend/
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = ROOT / "db" / "schema.sql"
ALEMBIC_0006 = ROOT / "alembic" / "versions" / "0006_device_stages.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---- schema.sql ----

def test_schema_sql_has_device_stages_table():
    sql = _read(SCHEMA_SQL)
    assert "CREATE TABLE device_stages" in sql
    assert "idx_device_stages_device" in sql
    assert "trg_device_stages_updated" in sql


def test_schema_sql_orders_batch_nullable():
    sql = _read(SCHEMA_SQL)
    # orders 批次行 4 字段放宽：去 NOT NULL，CHECK 改为容 NULL 形式
    assert "quantity INTEGER CHECK (quantity IS NULL OR quantity > 0)" in sql
    assert "unit_price DECIMAL(18,2) CHECK (unit_price IS NULL OR unit_price >= 0)" in sql


# ---- alembic 0006 ----

def test_alembic_0006_creates_device_stages():
    code = _read(ALEMBIC_0006)
    assert "CREATE TABLE device_stages" in code
    assert "idx_device_stages_device" in code
    assert "trg_device_stages_updated" in code


def test_alembic_0006_drops_orders_not_null():
    code = _read(ALEMBIC_0006)
    for col in ("equipment_model_id", "quantity", "unit_price", "total_amount"):
        assert f"ALTER TABLE orders ALTER COLUMN {col} DROP NOT NULL" in code


def test_alembic_0006_downgrade_guards_null_rows():
    """审计 Defect G：downgrade 回 SET NOT NULL 前须先清 NULL 行，否则破坏性失败。"""
    code = _read(ALEMBIC_0006)
    assert "def downgrade" in code
    assert "DELETE FROM orders" in code  # guard：先删 NULL 批次行再 SET NOT NULL
    for col in ("equipment_model_id", "quantity", "unit_price", "total_amount"):
        assert f"ALTER TABLE orders ALTER COLUMN {col} SET NOT NULL" in code


# ---- 0007 W5-6：assets 一机一卡 + operation_status；billings 索引迁 device 维度（H-1） ----

ALEMBIC_0007 = ROOT / "alembic" / "versions" / "0007_asset_per_device.py"


def test_schema_sql_assets_one_card_per_device():
    """schema.sql：operation_status 三态 + device_id 部分唯一 + 折旧字段放宽 nullable（建卡不折旧）。"""
    sql = _read(SCHEMA_SQL)
    assert "operation_status VARCHAR(20) NOT NULL DEFAULT '已转固未运营'" in sql
    assert "CHECK (operation_status IN ('已转固未运营','运营中','已处置'))" in sql
    assert "CREATE UNIQUE INDEX uq_assets_device ON assets(device_id)" in sql
    # 折旧字段放宽：CHECK 保留（>=0）但无 NOT NULL
    assert "residual_value DECIMAL(18,2) CHECK (residual_value >= 0)" in sql
    assert "monthly_depreciation DECIMAL(18,2) CHECK (monthly_depreciation >= 0)" in sql


def test_schema_sql_billing_index_on_device_dim():
    """H-1：billings 唯一索引在 device 维度，旧 order/sales_order 维不再现（schema.sql 为测试真相源）。"""
    sql = _read(SCHEMA_SQL)
    assert "CREATE UNIQUE INDEX uq_billing_period ON billings(device_id, period_index)" in sql
    assert "device_id IS NOT NULL" in sql
    # 旧维度漂移不再现（H-1 不复发）
    assert "uq_billing_period ON billings(order_id" not in sql
    assert "uq_billing_period ON billings(sales_order_id" not in sql


def test_alembic_0007_assets_columns_and_nullable():
    code = _read(ALEMBIC_0007)
    assert "ADD COLUMN device_id UUID REFERENCES devices(id)" in code
    assert "ADD COLUMN operation_status VARCHAR(20) NOT NULL DEFAULT '已转固未运营'" in code
    assert "CHECK (operation_status IN ('已转固未运营','运营中','已处置'))" in code
    assert "CREATE UNIQUE INDEX uq_assets_device" in code
    for col in ("start_date", "end_date", "residual_value",
                "depreciable_value", "annual_depreciation", "monthly_depreciation"):
        assert f"ALTER TABLE assets ALTER COLUMN {col} DROP NOT NULL" in code


def test_alembic_0007_billing_index_migrates_to_device_dim():
    code = _read(ALEMBIC_0007)
    assert "DROP INDEX IF EXISTS uq_billing_period" in code
    assert "CREATE UNIQUE INDEX uq_billing_period ON billings(device_id, period_index)" in code
    # upgrade 块不含旧维度（H-1 不复发）
    assert "CREATE UNIQUE INDEX uq_billing_period ON billings(sales_order_id, period_index)" not in code.split("def downgrade")[0]


def test_alembic_0007_invokes_bulk_split():
    code = _read(ALEMBIC_0007)
    assert "split_bulk_assets_to_per_device" in code


def test_alembic_0007_downgrade_guards_null_rows_and_restores_billing_index():
    """downgrade：回 NOT NULL 前先清 NULL 折旧行；billings 索引显式回旧维度（声明性，非无损）。"""
    code = _read(ALEMBIC_0007)
    assert "def downgrade" in code
    assert "DELETE FROM assets" in code  # guard：先删 NULL 折旧行再 SET NOT NULL
    for col in ("monthly_depreciation", "annual_depreciation", "depreciable_value",
                "residual_value", "end_date", "start_date"):
        assert f"ALTER TABLE assets ALTER COLUMN {col} SET NOT NULL" in code
    # billings 索引回旧维度（downgrade 显式声明；生产回滚需 DBA）
    assert "CREATE UNIQUE INDEX uq_billing_period ON billings(sales_order_id, period_index)" in code


# ---- 0008 W7-8：售后回租长期应付款 + 放款阈值/哨兵 + 预付款结转 + audit CHECK 扩 LEASEBACK_SALE ----

ALEMBIC_0008 = ROOT / "alembic" / "versions" / "0008_leaseback_and_disbursement.py"


def test_schema_sql_long_term_payables_table():
    """schema.sql：long_term_payables per-device 唯一 + 钩子位字段 + status CHECK。"""
    sql = _read(SCHEMA_SQL)
    assert "CREATE TABLE long_term_payables" in sql
    assert "CREATE UNIQUE INDEX uq_ltp_device ON long_term_payables(device_id)" in sql
    assert "idx_ltp_process" in sql
    # 钩子位字段（carrying/sale_gain_loss/original_end_date/paid_amount）
    assert "sale_gain_loss DECIMAL(18,2)" in sql  # 无 >= 0（损益可负）
    assert "CHECK (status IN ('已确认','部分偿还','已结清','已撤销'))" in sql


def test_schema_sql_orders_disbursement_and_devices_prepayment():
    """schema.sql：orders +放款阈值(0-100 CHECK)+哨兵；devices +prepayment_settled。"""
    sql = _read(SCHEMA_SQL)
    assert "disbursement_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 100" in sql
    assert "CHECK (disbursement_threshold_pct BETWEEN 0 AND 100)" in sql
    assert "disbursement_todo_process_id UUID REFERENCES leasing_processes(id)" in sql
    assert "prepayment_settled BOOLEAN NOT NULL DEFAULT FALSE" in sql


def test_schema_sql_audit_check_has_leaseback_sale_no_narrow():
    """audit_logs CHECK 扩 LEASEBACK_SALE 且不收窄（旧 17 枚举全在）。"""
    sql = _read(SCHEMA_SQL)
    assert "'LEASEBACK_SALE'" in sql
    # 旧 17 枚举全保留（不收窄）
    for old in ("'ALLOCATE_RETURN'", "'LIGHT_ON'", "'CONFIRM_UPLOAD'", "'ALLOCATE'"):
        assert old in sql


def test_alembic_0008_creates_table_columns_and_audit_check():
    code = _read(ALEMBIC_0008)
    assert "revision = \"0008_leaseback\"" in code
    assert 'down_revision = "0007_asset_per_device"' in code
    assert "CREATE TABLE long_term_payables" in code
    assert "CREATE UNIQUE INDEX uq_ltp_device" in code
    assert "ADD COLUMN disbursement_threshold_pct" in code
    assert "ADD COLUMN disbursement_todo_process_id" in code
    assert "ADD COLUMN prepayment_settled" in code
    # audit CHECK：先 DROP IF EXISTS 再 ADD（约束名 audit_logs_action_check，0004 已确认）
    assert "DROP CONSTRAINT IF EXISTS audit_logs_action_check" in code
    assert "'LEASEBACK_SALE'" in code


def test_alembic_0008_upgrade_does_not_narrow_audit_check():
    """upgrade 段的 audit CHECK 含全部旧 17 枚举 + LEASEBACK_SALE（只扩不收窄）。"""
    code = _read(ALEMBIC_0008)
    upgrade = code.split("def downgrade")[0]
    for old in ("'ALLOCATE_RETURN'", "'LIGHT_ON'", "'DISBURSE'", "'CONFIRM_UPLOAD'", "'ALLOCATE'"):
        assert old in upgrade
    assert "'LEASEBACK_SALE'" in upgrade


def test_alembic_0008_downgrade_is_lossless_reversible():
    """0008 无数据迁移 → 真·无损可逆：downgrade 反序 DROP 全部新对象 + audit CHECK 回旧 17。"""
    code = _read(ALEMBIC_0008)
    down = code.split("def downgrade")[1]
    assert "DROP COLUMN IF EXISTS prepayment_settled" in down
    assert "DROP COLUMN IF EXISTS disbursement_todo_process_id" in down
    assert "DROP COLUMN IF EXISTS disbursement_threshold_pct" in down
    assert "DROP TABLE IF EXISTS long_term_payables" in down
    assert "DROP INDEX IF EXISTS uq_ltp_device" in down
    # 无数据迁移语句（与 0007 split_bulk 不同）
    assert "split_bulk" not in code
    assert "DELETE FROM" not in down  # 无破坏性数据清理
