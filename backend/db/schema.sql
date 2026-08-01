-- ===========================================================================
-- SIEGPU 算力租赁 ERP — 数据库 schema（v2.0，含审计/复审修订）
-- Target: PostgreSQL 16
-- 约定：id UUID PK；created_at/updated_at TIMESTAMPTZ（触发器维护）；deleted_at 软删除；
--       rate 字段存小数（CHECK 0..1）；金额 DECIMAL(18,2)；direction 资金 IN/OUT、票据 RECEIVABLE/PAYABLE
-- 修订对应：NF1 调配幂等键分腿 / NF2 去 chk_reversal 子查询 / NF3 池余额靠反向记录抵消 /
--          NF4 对账 CTE 聚合（应用层）/ NF5 可调余额=净头寸正部（应用层）/ NF6 billings 唯一键含 order_id
-- ===========================================================================

-- updated_at 自动维护
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

-- ============================ 基础设施域 ============================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('FINANCE_DIRECTOR','PROCUREMENT','DELIVERY','FINANCE_STAFF','ADMIN')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_users_role ON users(role) WHERE deleted_at IS NULL;

-- ============================ 主数据域 ============================

CREATE TABLE suppliers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('设备供应商','资金供应商','其他')),
    contact_person VARCHAR(100),
    contact_phone VARCHAR(50),
    bank_account TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_suppliers_updated BEFORE UPDATE ON suppliers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    industry VARCHAR(100),
    contact_person VARCHAR(100),
    contact_phone VARCHAR(50),
    credit_rating VARCHAR(20),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_customers_updated BEFORE UPDATE ON customers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE equipment_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    category VARCHAR(20) NOT NULL CHECK (category IN ('大卡','小卡','组网设备')),
    gpu_type VARCHAR(100),
    gpu_count INTEGER CHECK (gpu_count IS NULL OR gpu_count > 0),
    memory VARCHAR(50),
    spec_json JSONB,
    unit_price_reference DECIMAL(18,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_equipment_models_updated BEFORE UPDATE ON equipment_models FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE banks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    contact_person VARCHAR(100),
    contact_phone VARCHAR(50),
    credit_line DECIMAL(18,2) CHECK (credit_line IS NULL OR credit_line >= 0),
    annual_rate NUMERIC(10,8) CHECK (annual_rate IS NULL OR annual_rate BETWEEN 0 AND 1),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_banks_updated BEFORE UPDATE ON banks FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 项目与合同域 ============================

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    code VARCHAR(50) UNIQUE,
    customer_id UUID REFERENCES customers(id),
    status VARCHAR(20) NOT NULL DEFAULT '进行中' CHECK (status IN ('进行中','暂停','已完成','已终止')),
    total_investment DECIMAL(18,2) CHECK (total_investment IS NULL OR total_investment >= 0),
    start_date DATE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_projects_updated BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_projects_status ON projects(status) WHERE deleted_at IS NULL;

CREATE TABLE contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    contract_no VARCHAR(100),
    type VARCHAR(20) NOT NULL CHECK (type IN ('SALES','PURCHASE')),
    party_type VARCHAR(20) NOT NULL CHECK (party_type IN ('supplier','customer')),
    party_id UUID NOT NULL,
    direction VARCHAR(12) NOT NULL CHECK (direction IN ('RECEIVABLE','PAYABLE')),
    amount DECIMAL(18,2) NOT NULL CHECK (amount >= 0),
    tax_rate NUMERIC(10,8) NOT NULL DEFAULT 0.13 CHECK (tax_rate BETWEEN 0 AND 1),
    monthly_rent DECIMAL(18,2) CHECK (monthly_rent IS NULL OR monthly_rent >= 0),
    start_date DATE,
    end_date DATE,
    parent_contract_id UUID REFERENCES contracts(id),
    status VARCHAR(20) NOT NULL DEFAULT '草稿' CHECK (status IN ('草稿','已签','执行中','已完成','已终止')),
    file_path VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK ((type='SALES' AND direction='RECEIVABLE') OR (type='PURCHASE' AND direction='PAYABLE'))
);
CREATE TRIGGER trg_contracts_updated BEFORE UPDATE ON contracts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_contracts_project ON contracts(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_contracts_type ON contracts(type) WHERE deleted_at IS NULL;

-- ============================ 金租流程域 ============================

CREATE TABLE leasing_processes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    total_amount DECIMAL(18,2) NOT NULL CHECK (total_amount > 0),
    actual_disbursement_amount DECIMAL(18,2) CHECK (actual_disbursement_amount IS NULL OR actual_disbursement_amount >= 0),
    annual_rate NUMERIC(10,8) CHECK (annual_rate IS NULL OR annual_rate BETWEEN 0 AND 1),
    term_periods SMALLINT CHECK (term_periods IS NULL OR term_periods > 0),
    payment_freq VARCHAR(12) CHECK (payment_freq IS NULL OR payment_freq IN ('月','季','半年')),
    repayment_method VARCHAR(12) CHECK (repayment_method IS NULL OR repayment_method IN ('等额本息','等额本金')),
    status VARCHAR(20) NOT NULL DEFAULT '进行中' CHECK (status IN ('进行中','已批','已放款','已拒绝')),
    start_date DATE,
    approval_date DATE,
    disbursement_date DATE,
    plan_generated BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_leasing_processes_updated BEFORE UPDATE ON leasing_processes FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_leasing_processes_project ON leasing_processes(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_leasing_processes_status ON leasing_processes(status) WHERE deleted_at IS NULL;

CREATE TABLE leasing_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id UUID NOT NULL REFERENCES leasing_processes(id),
    node_name VARCHAR(50) NOT NULL,
    seq INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '未开始' CHECK (status IN ('未开始','进行中','已完成','卡住')),
    planned_date DATE,
    actual_date DATE,
    owner_id UUID REFERENCES users(id),
    attachments JSONB,
    stuck_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_leasing_nodes_updated BEFORE UPDATE ON leasing_nodes FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_leasing_nodes_process ON leasing_nodes(process_id) WHERE deleted_at IS NULL;

-- ============================ 资金域 ============================

-- capital_transactions：invoice_id 的 FK 因与 invoices 互引用，稍后用 ALTER 添加（NF2：无 chk_reversal 子查询）
CREATE TABLE capital_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    source_type VARCHAR(20) NOT NULL CHECK (source_type IN ('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款')),
    direction VARCHAR(4) NOT NULL CHECK (direction IN ('IN','OUT')),
    amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
    transaction_date DATE NOT NULL,
    bank_id UUID REFERENCES banks(id),
    contract_id UUID REFERENCES contracts(id),
    leasing_process_id UUID REFERENCES leasing_processes(id),
    invoice_id UUID,                       -- FK 见下方 ALTER TABLE
    category VARCHAR(50),
    idempotency_key VARCHAR(128),
    reversal_of_id UUID REFERENCES capital_transactions(id),
    is_reversal BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_ct_idem ON capital_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_ct_project ON capital_transactions(project_id);
CREATE INDEX idx_ct_date ON capital_transactions(transaction_date);
CREATE INDEX idx_ct_source ON capital_transactions(source_type);
CREATE INDEX idx_ct_invoice ON capital_transactions(invoice_id);
CREATE TRIGGER trg_ct_updated BEFORE UPDATE ON capital_transactions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id UUID NOT NULL REFERENCES contracts(id),
    direction VARCHAR(12) NOT NULL CHECK (direction IN ('RECEIVABLE','PAYABLE')),
    invoice_no VARCHAR(100),
    amount DECIMAL(18,2) NOT NULL CHECK (amount >= 0),
    amount_ex_tax DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (amount_ex_tax >= 0),
    tax_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    tax_rate NUMERIC(10,8) NOT NULL DEFAULT 0.13 CHECK (tax_rate BETWEEN 0 AND 1),
    issue_date DATE,
    due_date DATE,
    paid_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT '待开' CHECK (status IN ('待开','已开','已收票','已付款','已红冲')),
    capital_transaction_id UUID REFERENCES capital_transactions(id),
    reversal_of_id UUID REFERENCES invoices(id),
    file_path VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (amount = ROUND(amount_ex_tax + tax_amount, 2))
);
CREATE INDEX idx_inv_contract ON invoices(contract_id);
CREATE INDEX idx_inv_direction ON invoices(direction);
CREATE TRIGGER trg_invoices_updated BEFORE UPDATE ON invoices FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 解决 capital_transactions <-> invoices 互引用
ALTER TABLE capital_transactions
    ADD CONSTRAINT fk_ct_invoice FOREIGN KEY (invoice_id) REFERENCES invoices(id);

CREATE TABLE capital_allocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_project_id UUID NOT NULL REFERENCES projects(id),
    to_project_id UUID NOT NULL REFERENCES projects(id),
    amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
    allocation_date DATE NOT NULL,
    expected_return_date DATE,
    actual_return_date DATE,
    reason TEXT,
    status VARCHAR(20) NOT NULL DEFAULT '已调配' CHECK (status IN ('已调配','已归还','逾期','已撤销')),
    approved_by UUID REFERENCES users(id),
    out_txn_id UUID REFERENCES capital_transactions(id),
    in_txn_id UUID REFERENCES capital_transactions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (from_project_id <> to_project_id)
);
CREATE INDEX idx_alloc_from ON capital_allocations(from_project_id);
CREATE INDEX idx_alloc_to ON capital_allocations(to_project_id);
CREATE TRIGGER trg_alloc_updated BEFORE UPDATE ON capital_allocations FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 交付与运营域 ============================

CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    contract_id UUID REFERENCES contracts(id),
    equipment_model_id UUID NOT NULL REFERENCES equipment_models(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(18,2) NOT NULL CHECK (unit_price >= 0),
    total_amount DECIMAL(18,2) NOT NULL CHECK (total_amount >= 0),
    order_date DATE,
    expected_delivery_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT '已下单' CHECK (status IN ('已下单','部分到货','已到货','已点亮')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_orders_project ON orders(project_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_orders_updated BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE delivery_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id),
    stage VARCHAR(20) NOT NULL CHECK (stage IN ('订货','到货','压测','运输在途','上架','点亮')),
    seq INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '未开始' CHECK (status IN ('未开始','进行中','已完成')),
    planned_date DATE,
    actual_date DATE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_ds_order ON delivery_stages(order_id);
CREATE TRIGGER trg_ds_updated BEFORE UPDATE ON delivery_stages FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- billings：计费/收入确认。唯一键 (order_id, period_index)（NF6）
CREATE TABLE billings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    contract_id UUID NOT NULL REFERENCES contracts(id),
    order_id UUID NOT NULL REFERENCES orders(id),
    period_index INTEGER NOT NULL CHECK (period_index > 0),
    period_label VARCHAR(20) NOT NULL,
    billing_date DATE NOT NULL,
    days_in_period INTEGER NOT NULL CHECK (days_in_period > 0),
    amount DECIMAL(18,2) NOT NULL CHECK (amount >= 0),
    amount_ex_tax DECIMAL(18,2) NOT NULL CHECK (amount_ex_tax >= 0),
    tax_amount DECIMAL(18,2) NOT NULL CHECK (tax_amount >= 0),
    tax_rate NUMERIC(10,8) NOT NULL DEFAULT 0.13 CHECK (tax_rate BETWEEN 0 AND 1),
    status VARCHAR(20) NOT NULL DEFAULT '未开' CHECK (status IN ('未开','已开','已收款','已红冲')),
    invoice_id UUID REFERENCES invoices(id),
    capital_transaction_id UUID REFERENCES capital_transactions(id),
    idempotency_key VARCHAR(128),
    reversal_of_id UUID REFERENCES billings(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (amount = ROUND(amount_ex_tax + tax_amount, 2))
);
CREATE UNIQUE INDEX uq_billing_period ON billings(order_id, period_index) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_billing_idem ON billings(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_billing_contract ON billings(contract_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_billings_updated BEFORE UPDATE ON billings FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE repayments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    leasing_process_id UUID NOT NULL REFERENCES leasing_processes(id),
    period INTEGER NOT NULL CHECK (period > 0),
    due_date DATE NOT NULL,
    planned_principal DECIMAL(18,2) NOT NULL CHECK (planned_principal >= 0),
    planned_interest DECIMAL(18,2) NOT NULL CHECK (planned_interest >= 0),
    actual_principal DECIMAL(18,2) CHECK (actual_principal IS NULL OR actual_principal >= 0),
    actual_interest DECIMAL(18,2) CHECK (actual_interest IS NULL OR actual_interest >= 0),
    paid_date DATE,
    capital_transaction_id UUID REFERENCES capital_transactions(id),
    status VARCHAR(20) NOT NULL DEFAULT '待还' CHECK (status IN ('待还','已还','逾期')),
    reversal_of_id UUID REFERENCES repayments(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_repay_process ON repayments(leasing_process_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_repay_due ON repayments(due_date) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_repayments_updated BEFORE UPDATE ON repayments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    equipment_model_id UUID NOT NULL REFERENCES equipment_models(id),
    order_id UUID REFERENCES orders(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_original_value DECIMAL(18,2) NOT NULL CHECK (unit_original_value >= 0),
    total_original_value DECIMAL(18,2) NOT NULL CHECK (total_original_value >= 0),
    residual_rate NUMERIC(10,8) NOT NULL DEFAULT 0.10 CHECK (residual_rate BETWEEN 0 AND 1),
    residual_value DECIMAL(18,2) NOT NULL CHECK (residual_value >= 0),
    depreciable_value DECIMAL(18,2) NOT NULL CHECK (depreciable_value >= 0),
    annual_depreciation DECIMAL(18,2) NOT NULL CHECK (annual_depreciation >= 0),
    monthly_depreciation DECIMAL(18,2) NOT NULL CHECK (monthly_depreciation >= 0),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '折旧中' CHECK (status IN ('折旧中','已提完')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_assets_project ON assets(project_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_assets_updated BEFORE UPDATE ON assets FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 审计与幂等（基础设施） ============================

-- audit_logs：append-only（应用 DB role 仅 INSERT/SELECT，REVOKE UPDATE/DELETE/TRUNCATE）
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    action VARCHAR(20) NOT NULL CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE')),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID,
    before_json JSONB,
    after_json JSONB,
    request_id VARCHAR(64),
    ip VARCHAR(45),
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_user_time ON audit_logs(user_id, at);

CREATE TABLE idempotency_keys (
    key VARCHAR(128) PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    endpoint VARCHAR(100) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    response_status SMALLINT,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_idem_created ON idempotency_keys(created_at);

-- ============================ 完成：19 张表 ============================
-- users, suppliers, customers, equipment_models, banks,
-- projects, contracts,
-- leasing_processes, leasing_nodes,
-- capital_transactions, invoices, capital_allocations,
-- orders, delivery_stages, billings, repayments, assets,
-- audit_logs, idempotency_keys
