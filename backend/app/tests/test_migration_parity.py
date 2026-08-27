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


# ---- 0011 二期 W3-4：contracts 收入核算路径判定 +7 字段（全 nullable，纯加法） ----

ALEMBIC_0011 = ROOT / "alembic" / "versions" / "0011_revenue_judge_fields.py"

JUDGE_COLS = ("pricing_authority", "inventory_risk_bearer", "principal_role",
              "revenue_method", "method_judge_basis", "method_confirmed_by", "method_confirmed_at")


def test_schema_sql_contracts_judge_fields():
    sql = _read(SCHEMA_SQL)
    for col in JUDGE_COLS:
        assert col in sql
    # 枚举 CHECK（容 NULL 形式，与 projects.business_type 同款）
    assert "pricing_authority IN ('自主定价','客户定价','上游定价')" in sql
    assert "inventory_risk_bearer IN ('我方','客户','上游')" in sql
    assert "principal_role IN ('主要责任人','代理人')" in sql
    assert "revenue_method IN ('总额法','净额法','经营租赁','服务费','待判定')" in sql
    assert "method_confirmed_by UUID REFERENCES users(id)" in sql


def test_alembic_0011_adds_contracts_judge_columns():
    code = _read(ALEMBIC_0011)
    assert 'revision = "0011_revenue_judge_fields"' in code
    assert 'down_revision = "0010_ebs_mock"' in code
    for col in JUDGE_COLS:
        assert f"ALTER TABLE contracts ADD COLUMN {col}" in code
    # audit CHECK 扩 REVENUE_JUDGE/REVENUE_OVERRIDE（只扩不收窄，含全部旧 18 枚举）
    upgrade = code.split("def downgrade")[0]
    assert "DROP CONSTRAINT IF EXISTS audit_logs_action_check" in upgrade
    for act in ("'REVENUE_JUDGE'", "'REVENUE_OVERRIDE'", "'LEASEBACK_SALE'", "'DISBURSE'"):
        assert act in upgrade


def test_alembic_0011_downgrade_drops_all_columns():
    """0011 downgrade：DROP 全部新列 + audit CHECK 回旧 18（先 DELETE 新动作行 guard，防收窄失败）。"""
    code = _read(ALEMBIC_0011)
    down = code.split("def downgrade")[1]
    for col in JUDGE_COLS:
        assert f"DROP COLUMN IF EXISTS {col}" in down
    # audit CHECK 收窄前的 guard：清 0011 新动作行（0007 DELETE guard 范式），否则存量行让 ADD CONSTRAINT 失败
    assert "DELETE FROM audit_logs WHERE action IN ('REVENUE_JUDGE','REVENUE_OVERRIDE')" in down
    # audit CHECK 回旧 18 枚举（新动作不出现在旧约束里）
    assert "'LEASEBACK_SALE'" in down
    assert "ADD CONSTRAINT audit_logs_action_check" in down


# ---- 0012 二期 W5-6：币种与汇率（3 新表 + 4 表加币种/汇率字段，全 nullable 纯加法） ----

ALEMBIC_0012 = ROOT / "alembic" / "versions" / "0012_currency_exchange.py"

FX_NEW_TABLES = ("currencies", "exchange_rates", "exchange_gain_loss_rules")
FX_COLS = (("contracts", "currency_code"), ("contracts", "booked_rate"),
           ("invoices", "currency_code"), ("invoices", "invoice_rate"),
           ("billings", "currency_code"), ("billings", "booked_rate"),
           ("capital_transactions", "currency_code"), ("capital_transactions", "settlement_rate"),
           ("capital_transactions", "base_amount"))


def test_schema_sql_fx_new_tables():
    sql = _read(SCHEMA_SQL)
    for t in FX_NEW_TABLES:
        assert f"CREATE TABLE {t}" in sql
    assert "rate DECIMAL(18,8) NOT NULL CHECK (rate > 0)" in sql  # 率全精度，永不 round（D6 对照表）
    assert "uq_currencies_code" in sql
    assert "idx_fx_rates_lookup" in sql


def test_schema_sql_fx_existing_table_columns():
    sql = _read(SCHEMA_SQL)
    for _tbl, col in FX_COLS:
        assert col in sql
    # source_type CHECK 含汇兑损益（只扩不收窄）
    assert "'汇兑损益'" in sql
    assert "'租金收入'" in sql


def test_alembic_0012_creates_tables_and_columns():
    code = _read(ALEMBIC_0012)
    assert 'revision = "0012_currency_exchange"' in code
    assert 'down_revision = "0011_revenue_judge_fields"' in code
    for t in FX_NEW_TABLES:
        assert f"CREATE TABLE {t}" in code
    for tbl, col in FX_COLS:
        assert f"ALTER TABLE {tbl} ADD COLUMN {col}" in code
    upgrade = code.split("def downgrade")[0]
    assert "'汇兑损益'" in upgrade and "'归还自有'" in upgrade  # CHECK 只扩不收窄


def test_alembic_0012_downgrade_reversible():
    """0012 无数据迁移 → 无损可逆：DROP 全部新对象 + source_type CHECK 回旧 9 枚举（先 DELETE guard）。"""
    code = _read(ALEMBIC_0012)
    down = code.split("def downgrade")[1]
    for t in FX_NEW_TABLES:
        assert f"DROP TABLE IF EXISTS {t}" in down
    for _tbl, col in FX_COLS:
        assert f"DROP COLUMN IF EXISTS {col}" in down
    # CHECK 收窄前清汇兑损益流水（0011 guard 范式）；旧 9 枚举经模块常量 _CT_SOURCE_OLD 回写
    assert "DELETE FROM capital_transactions WHERE source_type = '汇兑损益'" in down
    assert "ADD CONSTRAINT capital_transactions_source_type_check" in down
    assert "_CT_SOURCE_OLD" in down
    assert "'归还自有'" in code  # 旧枚举全集在模块常量中（upgrade/downgrade 共用校验）


# ---- 0013 二期 W7-8：保险管理（3 新表，纯加法） ----

ALEMBIC_0013 = ROOT / "alembic" / "versions" / "0013_insurance.py"

INS_TABLES = ("insurance_policies", "insurance_policy_devices", "insurance_configs")


def test_schema_sql_insurance_tables():
    sql = _read(SCHEMA_SQL)
    for t in INS_TABLES:
        assert f"CREATE TABLE {t}" in sql
        assert f"trg_" in sql
    # 硬约束枚举：险种 / 归集口径 / 状态
    assert "policy_type IN ('运输险','财产险')" in sql
    assert "cost_allocation IS NULL OR cost_allocation IN ('资产原值','长期待摊')" in sql
    assert "status IN ('待确认','已生效','理赔中','已到期','已退保')" in sql
    assert "uq_inspd_policy_device" in sql
    assert "collected_at TIMESTAMPTZ" in sql  # 归集幂等守卫


def test_alembic_0013_creates_tables():
    code = _read(ALEMBIC_0013)
    assert 'revision = "0013_insurance"' in code
    assert 'down_revision = "0012_currency_exchange"' in code
    for t in INS_TABLES:
        assert f"CREATE TABLE {t}" in code
        assert f"DROP TABLE IF EXISTS {t}" in code.split("def downgrade")[1]


# ---- 0014 二期 W9-10：合同深化 + 单据编号 + 金租规则（4 新表 + devices/ contracts 加列，纯加法） ----

ALEMBIC_0014 = ROOT / "alembic" / "versions" / "0014_contract_ext.py"

W910_TABLES = ("contract_amendments", "contract_terminations", "doc_number_rules", "leasing_rule_configs")
W910_CONTRACT_COLS = ("purchase_type", "delivery_terms", "warranty_terms",
                      "penalty_terms", "prepayment_ratio", "collection_account_type")


def test_schema_sql_w910_tables_and_columns():
    sql = _read(SCHEMA_SQL)
    for t in W910_TABLES:
        assert f"CREATE TABLE {t}" in sql
    for col in W910_CONTRACT_COLS:
        assert col in sql
    assert "prepayment_settled_amount" in sql  # D2：devices 单源结转列
    assert "uq_docnum_type" in sql


def test_alembic_0014_creates_and_drops_all():
    code = _read(ALEMBIC_0014)
    assert 'revision = "0014_contract_ext"' in code
    assert 'down_revision = "0013_insurance"' in code
    for t in W910_TABLES:
        assert f"CREATE TABLE {t}" in code
    assert "ALTER TABLE devices ADD COLUMN prepayment_settled_amount" in code
    down = code.split("def downgrade")[1]
    for t in W910_TABLES:
        assert f"DROP TABLE IF EXISTS {t}" in down
    for col in W910_CONTRACT_COLS:
        assert f"ADD COLUMN {col}" in code
        assert f"DROP COLUMN IF EXISTS {col}" in down
    assert "DROP COLUMN IF EXISTS prepayment_settled_amount" in down


# ---- 0015 二期 W11-12：付款管控 + 通用审批 + 进项税（3 新表 + invoices 进项字段） ----

ALEMBIC_0015 = ROOT / "alembic" / "versions" / "0015_payment_approval.py"

W1112_TABLES = ("approvals", "payment_requests", "payment_settlements")


def test_schema_sql_w1112_tables_and_invoice_fields():
    sql = _read(SCHEMA_SQL)
    for t in W1112_TABLES:
        assert f"CREATE TABLE {t}" in sql
    assert "certification_status" in sql and "certification_date" in sql
    assert "'未认证','已认证','已抵扣'" in sql
    assert "idx_payset_device" in sql  # 逐台分摊索引
    assert "uq_" not in "payment_settlements"  # 多对多无唯一约束（同发票可多行：逐台拆分）


def test_alembic_0015_creates_and_drops_all():
    code = _read(ALEMBIC_0015)
    assert 'revision = "0015_payment_approval"' in code
    assert 'down_revision = "0014_contract_ext"' in code
    for t in W1112_TABLES:
        assert f"CREATE TABLE {t}" in code
        assert f"DROP TABLE IF EXISTS {t}" in code.split("def downgrade")[1]
    assert "ALTER TABLE invoices ADD COLUMN certification_status" in code
    down = code.split("def downgrade")[1]
    assert "DROP COLUMN IF EXISTS certification_status" in down
    assert "DROP COLUMN IF EXISTS certification_date" in down


# ---- 0016 三期 §4.2：收入确认 + 科目映射（2 新表，纯加法） ----

ALEMBIC_0016 = ROOT / "alembic" / "versions" / "0016_revenue_recognition.py"


def test_schema_sql_revenue_recognition_tables():
    sql = _read(SCHEMA_SQL)
    assert "CREATE TABLE revenue_recognitions" in sql
    assert "CREATE TABLE gl_account_mappings" in sql
    assert "uq_revrec_billing" in sql  # 同 billing 幂等
    assert "status IN ('草稿','已确认','已同步EBS')" in sql
    assert "uq_glam_event_method" in sql


def test_alembic_0016_creates_and_drops_all():
    code = _read(ALEMBIC_0016)
    assert 'revision = "0016_revenue_recognition"' in code
    assert 'down_revision = "0015_payment_approval"' in code
    down = code.split("def downgrade")[1]
    for t in ("revenue_recognitions", "gl_account_mappings"):
        assert f"CREATE TABLE {t}" in code
        assert f"DROP TABLE IF EXISTS {t}" in down


# ---- 0017 三期 §4.4：采购退货（2 新表 + devices.status CHECK 扩'已退货'） ----

ALEMBIC_0017 = ROOT / "alembic" / "versions" / "0017_return_orders.py"


def test_schema_sql_return_orders():
    sql = _read(SCHEMA_SQL)
    assert "CREATE TABLE return_orders" in sql
    assert "CREATE TABLE return_order_devices" in sql
    assert "uq_return_device" in sql
    assert "'已退货'" in sql  # devices.status CHECK 扩枚举
    assert "return_type IN ('到货不合格','压测不通过','合同终止')" in sql


def test_alembic_0017_creates_and_drops_all():
    code = _read(ALEMBIC_0017)
    assert 'revision = "0017_return_orders"' in code
    assert 'down_revision = "0016_revenue_recognition"' in code
    down = code.split("def downgrade")[1]
    for t in ("return_orders", "return_order_devices"):
        assert f"CREATE TABLE {t}" in code
        assert f"DROP TABLE IF EXISTS {t}" in down
    # CHECK 只扩不收窄 + downgrade 先清'已退货'行 guard
    assert "'点亮验收','已退货'" in code.split("def downgrade")[0]
    assert "DELETE FROM devices WHERE status = '已退货'" in down
    assert "'已退货'" not in down.split("ADD CONSTRAINT")[1]  # 旧 CHECK 不含已退货


# ---- 0020 W4：销售分批次验收（sales_orders 批次字段 + sales_batch_devices + acceptance_records.shelve） ----

ALEMBIC_0020 = ROOT / "alembic" / "versions" / "0020_sales_batch_acceptance.py"


def test_schema_sql_sales_batch():
    sql = _read(SCHEMA_SQL)
    assert "is_batch BOOLEAN NOT NULL DEFAULT FALSE" in sql  # sales_orders 批次载体
    assert "batch_name VARCHAR(100)" in sql
    assert "CREATE TABLE sales_batch_devices" in sql
    assert "uq_sbd_active_device" in sql
    assert "shelve BOOLEAN NOT NULL DEFAULT FALSE" in sql  # acceptance_records 上架同步标记


def test_alembic_0020_creates_and_drops_all():
    code = _read(ALEMBIC_0020)
    assert 'revision = "0020_sales_batch_acceptance"' in code
    assert 'down_revision = "0019_disbursement_acceptance"' in code
    assert "CREATE TABLE IF NOT EXISTS sales_batch_devices" in code
    assert "ADD COLUMN IF NOT EXISTS is_batch" in code
    assert "ADD COLUMN IF NOT EXISTS batch_name" in code
    assert "ADD COLUMN IF NOT EXISTS shelve" in code
    down = code.split("def downgrade")[1]
    assert "DROP COLUMN IF EXISTS shelve" in down
    assert "DROP TABLE IF EXISTS sales_batch_devices" in down
    assert "DROP COLUMN IF EXISTS is_batch" in down


# ---- 0021 四期 W4：合同类型 + 金额含税化（contracts + biz_type/amount_incl_tax/lease_months，纯加法） ----

ALEMBIC_0021 = ROOT / "alembic" / "versions" / "0021_contract_biz_type.py"


def test_schema_sql_contract_biz_type():
    sql = _read(SCHEMA_SQL)
    assert "biz_type IN ('算力租赁','转售','服务')" in sql
    assert "amount_incl_tax DECIMAL(18,2)" in sql
    assert "lease_months INTEGER" in sql


def test_alembic_0021_creates_and_backfills():
    code = _read(ALEMBIC_0021)
    assert 'revision = "0021_contract_biz_type"' in code
    assert 'down_revision = "0020_sales_batch_acceptance"' in code
    assert "ADD COLUMN IF NOT EXISTS biz_type" in code
    assert "ADD COLUMN IF NOT EXISTS amount_incl_tax" in code
    assert "ADD COLUMN IF NOT EXISTS lease_months" in code
    # 存量回填：含税 = 不含税 × (1+税率)
    assert "UPDATE contracts SET amount_incl_tax = ROUND(amount * (1 + tax_rate), 2)" in code
    down = code.split("def downgrade")[1]
    for col in ("biz_type", "amount_incl_tax", "lease_months"):
        assert f"DROP COLUMN IF EXISTS {col}" in down


# ---- 0022 四期 W4 期1：资金池分池（capital_transactions + pool 列 + source_type 扩枚举） ----

ALEMBIC_0022 = ROOT / "alembic" / "versions" / "0022_capital_pools.py"


def test_schema_sql_capital_pool():
    sql = _read(SCHEMA_SQL)
    assert "pool VARCHAR(20) NOT NULL DEFAULT 'OWN' CHECK (pool IN ('OWN','LEASING','BANK','PREPAY'))" in sql
    assert "'预付','归还银行'" in sql  # source_type CHECK 扩枚举
    assert "idx_ct_pool" in sql


def test_alembic_0022_pool_and_source_type():
    code = _read(ALEMBIC_0022)
    assert 'revision = "0022_capital_pools"' in code
    assert 'down_revision = "0021_contract_biz_type"' in code
    assert "ADD COLUMN IF NOT EXISTS pool" in code
    assert "pool IN ('OWN','LEASING','BANK','PREPAY')" in code
    # source_type CHECK 扩 '预付'/'归还银行'
    assert "'预付','归还银行'" in code
    # 存量回填：金租融资→LEASING；银行流贷/归还流贷→BANK
    assert "SET pool='LEASING' WHERE source_type='金租融资'" in code
    assert "SET pool='BANK' WHERE source_type IN ('银行流贷','归还流贷','归还银行')" in code
    down = code.split("def downgrade")[1]
    assert "DROP COLUMN IF EXISTS pool" in down


# ---- 0023 四期 W4 期2：收入按开票确认（revenue_recognitions + invoice_id 幂等） ----

ALEMBIC_0023 = ROOT / "alembic" / "versions" / "0023_revenue_from_invoice.py"


def test_schema_sql_revenue_invoice_id():
    sql = _read(SCHEMA_SQL)
    assert "invoice_id UUID REFERENCES invoices(id)" in sql
    assert "uq_rr_invoice" in sql


def test_alembic_0023_revenue_invoice():
    code = _read(ALEMBIC_0023)
    assert 'revision = "0023_revenue_from_invoice"' in code
    assert 'down_revision = "0022_capital_pools"' in code
    assert "ADD COLUMN IF NOT EXISTS invoice_id" in code
    assert "uq_rr_invoice" in code
    down = code.split("def downgrade")[1]
    assert "DROP COLUMN IF EXISTS invoice_id" in down

# ---- 0024 智能助手（对话大脑 P0）：assistant_sessions + assistant_messages（2 新表，纯加法） ----

ALEMBIC_0024 = ROOT / "alembic" / "versions" / "0024_assistant.py"

ASST_TABLES = ("assistant_sessions", "assistant_messages")


def test_schema_sql_assistant_tables():
    sql = _read(SCHEMA_SQL)
    for t in ASST_TABLES:
        assert f"CREATE TABLE {t}" in sql
    assert "uq_asst_session_channel" in sql
    assert "idx_asst_msg_session" in sql
    assert "trg_asst_sessions_updated" in sql
    assert "trg_asst_messages_updated" in sql
    assert "role IN ('user','assistant','tool')" in sql


def test_alembic_0024_creates_and_drops_all():
    code = _read(ALEMBIC_0024)
    assert 'revision = "0024_assistant"' in code
    assert 'down_revision = "0023_revenue_from_invoice"' in code
    for t in ASST_TABLES:
        assert f"CREATE TABLE {t}" in code
    down = code.split("def downgrade")[1]
    for t in ASST_TABLES:
        assert f"DROP TABLE IF EXISTS {t}" in down
    # 纯加表无损可逆：downgrade 无数据清理语句
    assert "DELETE FROM" not in down
# ---- 0025 助手反馈与问题缺口（体验包 #7）：messages + feedback；assistant_gaps 新表 ----

ALEMBIC_0025 = ROOT / "alembic" / "versions" / "0025_assistant_feedback.py"


def test_schema_sql_assistant_feedback():
    sql = _read(SCHEMA_SQL)
    assert "feedback VARCHAR(8)" in sql
    assert "CREATE TABLE assistant_gaps" in sql
    assert "idx_asst_gap_user" in sql
    assert "trg_asst_gaps_updated" in sql


def test_alembic_0025_creates_and_drops_all():
    code = _read(ALEMBIC_0025)
    assert 'revision = "0025_assistant_feedback"' in code
    assert 'down_revision = "0024_assistant"' in code
    assert "ADD COLUMN IF NOT EXISTS feedback" in code
    assert "CREATE TABLE assistant_gaps" in code
    down = code.split("def downgrade")[1]
    assert "DROP TABLE IF EXISTS assistant_gaps" in down
    assert "DROP COLUMN IF EXISTS feedback" in down
    assert "DELETE FROM" not in down
# ---- 0026 认知沉淀（M-A）----

def test_schema_sql_assistant_cognition():
    sql = _read(SCHEMA_SQL)
    assert "CREATE TABLE assistant_cognition" in sql
    assert "uq_asst_cog_user_key" in sql
    assert "kind IN ('entity_alias','glossary_pref','query_hint')" in sql
    assert "source IN ('auto','user')" in sql


def test_alembic_0026_creates_and_drops_all():
    code = _read(ROOT / "alembic" / "versions" / "0026_assistant_cognition.py")
    assert 'revision = "0026_assistant_cognition"' in code
    assert 'down_revision = "0025_assistant_feedback"' in code
    assert "CREATE TABLE assistant_cognition" in code
    down = code.split("def downgrade")[1]
    assert "DROP TABLE IF EXISTS assistant_cognition" in down
    assert "DELETE FROM" not in down
# ---- 0027 写操作确认令牌（M-C）----

def test_schema_sql_confirm_tokens_and_audit_widen():
    sql = _read(SCHEMA_SQL)
    assert "CREATE TABLE assistant_confirm_tokens" in sql
    assert "idempotency_key VARCHAR(128) NOT NULL UNIQUE" in sql
    assert "idx_asst_ct_user_used" in sql
    # audit CHECK 扩枚举：旧 20 值全保留 + ASSISTANT_WRITE（只扩不窄）
    assert "'REVENUE_OVERRIDE','ASSISTANT_WRITE'" in sql
    assert "'ALLOCATE'" in sql


def test_alembic_0027_creates_drops_and_guards():
    code = _read(ROOT / "alembic" / "versions" / "0027_assistant_writes.py")
    assert 'revision = "0027_assistant_writes"' in code
    assert 'down_revision = "0026_assistant_cognition"' in code
    assert "CREATE TABLE assistant_confirm_tokens" in code
    down = code.split("def downgrade")[1]
    assert "DROP TABLE IF EXISTS assistant_confirm_tokens" in down
    # 收窄前先清 ASSISTANT_WRITE 行（0008/0011 guard 范式）
    assert "DELETE FROM audit_logs WHERE action = 'ASSISTANT_WRITE'" in down
    # upgrade 段 CHECK 含全部旧枚举（只扩不窄）
    upgrade = code.split("def downgrade")[0]
    for act in ("'ALLOCATE'", "'REVENUE_OVERRIDE'", "'LEASEBACK_SALE'"):
        assert act in code