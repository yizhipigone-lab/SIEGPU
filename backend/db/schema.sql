-- ===========================================================================
-- SIEGPU 算力租赁 ERP — 数据库 schema（v3.1，全链路补齐）
-- Target: PostgreSQL 16
-- 约定：id UUID PK；created_at/updated_at TIMESTAMPTZ（触发器维护）；deleted_at 软删除；
--       rate 字段存小数（CHECK 0..1）；金额 DECIMAL(18,2)；direction 资金 IN/OUT、票据 RECEIVABLE/PAYABLE
-- 修订：v3.1 — 新增5表(sales_orders/acceptance_records/funding_replacements/profit_scenarios/service_confirmations)
--            扩展 capital_transactions(+is_replaced+replaced_amount, CHECK+归还流贷/归还自有)
--            扩展 invoices(+billing_id+purchase_order_id+reconciled_*, CHECK+待收票/已回款/已核销)
--            扩展 billings(+sales_order_id+confirmation_status, order_id→nullable, 唯一索引重建)
--            扩展 audit_logs(CHECK+ACCEPT_APPROVE/RECONCILE等)
-- 修订：一期W1-2 — 新增3表(devices/batch_devices/off_balance_registers)
--            扩展 projects(+business_type+leasing_mode+parent_id+financing_plan, status CHECK+筹备中)
--            扩展 equipment_models(+resource_attr+billing_modes) suppliers(+is_leasing_org+leasing_coop_modes)
--            扩展 orders(+is_batch+batch_name+batch_status+flow_type) contracts(+leasing_mode)
--            扩展 leasing_processes(+leasing_mode+financing_type+materials) billings(+device_id)
-- 修订：二期W3-4 — 扩展 contracts(+pricing_authority+inventory_risk_bearer+principal_role
--            +revenue_method+method_judge_basis+method_confirmed_by+method_confirmed_at, 全nullable, 迁移0011)
-- 修订：二期W5-6 — 新增3表(currencies/exchange_rates/exchange_gain_loss_rules)
--            扩展 contracts(+currency_code+booked_rate) invoices(+currency_code+invoice_rate)
--            billings(+currency_code+booked_rate) capital_transactions(+currency_code+settlement_rate+base_amount,
--            source_type CHECK+汇兑损益)（全nullable, 迁移0012）
-- 修订：二期W7-8 — 新增3表(insurance_policies/insurance_policy_devices/insurance_configs, 迁移0013)
-- 修订：二期W9-10 — 新增4表(contract_amendments/contract_terminations/doc_number_rules/leasing_rule_configs)
--            扩展 devices(+prepayment_settled_amount) contracts(+6深化字段)（迁移0014）
-- 修订：二期W11-12 — 新增3表(approvals/payment_requests/payment_settlements)
--            扩展 invoices(+certification_status+certification_date)（迁移0015）
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
    is_leasing_org BOOLEAN NOT NULL DEFAULT FALSE,
    leasing_coop_modes JSONB,
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
    resource_attr VARCHAR(20) CHECK (resource_attr IS NULL OR resource_attr IN ('自购资产','金租资产','转售资源')),
    billing_modes JSONB,
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
    status VARCHAR(20) NOT NULL DEFAULT '进行中' CHECK (status IN ('筹备中','进行中','暂停','已完成','已终止')),
    total_investment DECIMAL(18,2) CHECK (total_investment IS NULL OR total_investment >= 0),
    start_date DATE,
    notes TEXT,
    business_type VARCHAR(20) CHECK (business_type IS NULL OR business_type IN ('经营租赁','转售','自营')),
    leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租')),
    parent_id UUID REFERENCES projects(id),
    financing_plan JSONB,
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
    leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租')),
    -- 二期 W3-4：收入核算路径判定（迁移 0011；输入 3 字段 + 判定快照 + 确认留痕，全 nullable）
    pricing_authority VARCHAR(20) CHECK (pricing_authority IS NULL OR pricing_authority IN ('自主定价','客户定价','上游定价')),
    inventory_risk_bearer VARCHAR(20) CHECK (inventory_risk_bearer IS NULL OR inventory_risk_bearer IN ('我方','客户','上游')),
    principal_role VARCHAR(20) CHECK (principal_role IS NULL OR principal_role IN ('主要责任人','代理人')),
    revenue_method VARCHAR(20) CHECK (revenue_method IS NULL OR revenue_method IN ('总额法','净额法','经营租赁','服务费','待判定')),
    method_judge_basis TEXT,
    method_confirmed_by UUID REFERENCES users(id),
    method_confirmed_at TIMESTAMPTZ,
    -- 二期 W5-6：币种与签约记账汇率（迁移 0012；NULL=人民币，存量语义不变）
    currency_code VARCHAR(10),
    booked_rate DECIMAL(18,8),
    -- 二期 W9-10：合同深化（迁移 0014，全 nullable）
    purchase_type VARCHAR(20),           -- 采购类型（设备/服务/其他）
    delivery_terms VARCHAR(200),         -- 交付条款
    warranty_terms VARCHAR(200),         -- 质保条款
    penalty_terms VARCHAR(200),          -- 违约条款
    prepayment_ratio NUMERIC(10,8),      -- 预付款比例（小数）
    collection_account_type VARCHAR(20), -- 销售收款账户类型（监管户/一般户）
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK ((type='SALES' AND direction='RECEIVABLE') OR (type='PURCHASE' AND direction='PAYABLE'))
);
CREATE TRIGGER trg_contracts_updated BEFORE UPDATE ON contracts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_contracts_project ON contracts(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_contracts_type ON contracts(type) WHERE deleted_at IS NULL;

-- ============================ 销售订单（v3.1 新增） ============================

CREATE TABLE sales_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    contract_id UUID NOT NULL REFERENCES contracts(id),
    equipment_model_id UUID NOT NULL REFERENCES equipment_models(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    monthly_rent_per_unit DECIMAL(18,2) NOT NULL CHECK (monthly_rent_per_unit >= 0),
    total_monthly_rent DECIMAL(18,2) NOT NULL CHECK (total_monthly_rent >= 0),
    start_date DATE,
    end_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT '待交付' CHECK (status IN ('待交付','执行中','已终止','已完成')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_sales_orders_updated BEFORE UPDATE ON sales_orders FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_sales_orders_project ON sales_orders(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_sales_orders_contract ON sales_orders(contract_id) WHERE deleted_at IS NULL;

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
    leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租')),
    financing_type VARCHAR(30) CHECK (financing_type IS NULL OR financing_type IN ('金租直租','金租回租','银行流贷','项目贷款')),
    materials JSONB,
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

-- capital_transactions：v3.1 source_type CHECK 扩展 + is_replaced/replaced_amount
CREATE TABLE capital_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    source_type VARCHAR(20) NOT NULL CHECK (source_type IN ('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款','归还流贷','归还自有','汇兑损益')),
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
    is_replaced BOOLEAN NOT NULL DEFAULT FALSE,
    replaced_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (replaced_amount >= 0),
    note TEXT,
    created_by UUID REFERENCES users(id),
    -- 二期 W5-6：币种/结算汇率/本币金额（迁移 0012；currency NULL=人民币；base_amount 恒人民币，仅外币有值）
    currency_code VARCHAR(10),
    settlement_rate DECIMAL(18,8),
    base_amount DECIMAL(18,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_ct_idem ON capital_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_ct_project ON capital_transactions(project_id);
CREATE INDEX idx_ct_date ON capital_transactions(transaction_date);
CREATE INDEX idx_ct_source ON capital_transactions(source_type);
CREATE INDEX idx_ct_invoice ON capital_transactions(invoice_id);
CREATE INDEX idx_ct_replaced ON capital_transactions(project_id, is_replaced) WHERE deleted_at IS NULL AND direction = 'OUT';
CREATE TRIGGER trg_ct_updated BEFORE UPDATE ON capital_transactions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 资金置换记录（v3.1 新增）
CREATE TABLE funding_replacements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    leasing_process_id UUID REFERENCES leasing_processes(id),
    original_txn_id UUID NOT NULL REFERENCES capital_transactions(id),
    replacement_txn_id UUID NOT NULL REFERENCES capital_transactions(id),
    amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
    source_type_replaced VARCHAR(20) NOT NULL CHECK (source_type_replaced IN ('银行流贷','自有资金')),
    replacement_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '已置换' CHECK (status IN ('已置换','已撤销')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_fr_pair ON funding_replacements(original_txn_id, replacement_txn_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_fr_project ON funding_replacements(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_fr_leasing ON funding_replacements(leasing_process_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_funding_replacements_updated BEFORE UPDATE ON funding_replacements FOR EACH ROW EXECUTE FUNCTION set_updated_at();

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
    status VARCHAR(20) NOT NULL DEFAULT '待开' CHECK (status IN ('待开','已开','待收票','已收票','已回款','已付款','已核销','已红冲')),
    billing_id UUID,                       -- FK 见下方 ALTER TABLE
    purchase_order_id UUID,                   -- FK 见末尾
    capital_transaction_id UUID REFERENCES capital_transactions(id),
    reconciled_at DATE,
    reconciled_by UUID REFERENCES users(id),
    reconciliation_note TEXT,
    reversal_of_id UUID REFERENCES invoices(id),
    file_path VARCHAR(500),
    -- 二期 W11-12：进项侧认证/抵扣（迁移 0015，审计 A10；NULL=未涉及进项流程）
    certification_status VARCHAR(20) CHECK (certification_status IS NULL OR certification_status IN ('未认证','已认证','已抵扣')),
    certification_date DATE,
    -- 二期 W5-6：币种与开票日汇率（迁移 0012；NULL=人民币）
    currency_code VARCHAR(10),
    invoice_rate DECIMAL(18,8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (amount = ROUND(amount_ex_tax + tax_amount, 2))
);
CREATE INDEX idx_inv_contract ON invoices(contract_id);
CREATE INDEX idx_inv_direction ON invoices(direction);
CREATE INDEX idx_inv_billing ON invoices(billing_id) WHERE billing_id IS NOT NULL;
CREATE TRIGGER trg_invoices_updated BEFORE UPDATE ON invoices FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 互引用 FK 在所有表创建完毕后添加

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
    equipment_model_id UUID REFERENCES equipment_models(id),  -- 一期 W3-4：批次行可空（跨型号组合）
    quantity INTEGER CHECK (quantity IS NULL OR quantity > 0),  -- 批次行可空
    unit_price DECIMAL(18,2) CHECK (unit_price IS NULL OR unit_price >= 0),  -- 批次行可空
    total_amount DECIMAL(18,2) CHECK (total_amount IS NULL OR total_amount >= 0),  -- 批次行可空
    order_date DATE,
    expected_delivery_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT '已下单' CHECK (status IN ('已下单','部分到货','已到货','已点亮')),
    is_batch BOOLEAN NOT NULL DEFAULT FALSE,
    batch_name VARCHAR(100),
    batch_status VARCHAR(20),
    flow_type VARCHAR(20) CHECK (flow_type IS NULL OR flow_type IN ('batch','device','transfer-resale')),
    disbursement_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 100 CHECK (disbursement_threshold_pct BETWEEN 0 AND 100),  -- 一期 W7-8：放款阈值百分比（应用层÷100）
    disbursement_todo_process_id UUID REFERENCES leasing_processes(id),  -- 一期 W7-8：达阈值自动建 leasing 的幂等哨兵
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

-- ============================ 设备实体层（一期 W1-2 新增） ============================

-- devices：单台设备档案。status 为物化列（一期 W3-4 起由设备状态机单点维护）
CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sn VARCHAR(50) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES projects(id),
    order_id UUID REFERENCES orders(id),
    batch_id UUID REFERENCES orders(id),
    sales_contract_id UUID REFERENCES contracts(id),
    equipment_model_id UUID NOT NULL REFERENCES equipment_models(id),
    supplier_id UUID REFERENCES suppliers(id),
    monthly_price DECIMAL(18,2) CHECK (monthly_price IS NULL OR monthly_price >= 0),
    config JSONB,
    leasing_mode VARCHAR(20) CHECK (leasing_mode IS NULL OR leasing_mode IN ('自有','直租','售后回租')),
    purchase_value DECIMAL(18,2) CHECK (purchase_value IS NULL OR purchase_value >= 0),
    prepayment_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (prepayment_amount >= 0),
    status VARCHAR(20) NOT NULL DEFAULT '订货' CHECK (status IN ('订货','在途','到货','己方压测','上架','客户压测','点亮验收')),
    ownership VARCHAR(20) CHECK (ownership IS NULL OR ownership IN ('表内自有','金租表外','转售表外')),
    prepayment_settled BOOLEAN NOT NULL DEFAULT FALSE,  -- 一期 W7-8：售后回租预付款结转标记
    prepayment_settled_amount DECIMAL(18,2) CHECK (prepayment_settled_amount IS NULL OR prepayment_settled_amount >= 0),  -- 二期 W9-10：累计已结转（D2 复用 devices 单源，迁移 0014）
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_devices_project ON devices(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_devices_batch ON devices(batch_id) WHERE deleted_at IS NULL AND batch_id IS NOT NULL;
CREATE INDEX idx_devices_status ON devices(status) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_devices_updated BEFORE UPDATE ON devices FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- batch_devices：批次-设备组合关系（留痕）；同一台设备全局仅一条 active 记录
CREATE TABLE batch_devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES orders(id),
    device_id UUID NOT NULL REFERENCES devices(id),
    action VARCHAR(10) NOT NULL CHECK (action IN ('加入','移出')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    operated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_batch_devices_active ON batch_devices(device_id) WHERE active AND deleted_at IS NULL;
CREATE INDEX idx_bd_batch ON batch_devices(batch_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_bd_updated BEFORE UPDATE ON batch_devices FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- off_balance_registers：表外设备备查台账（独立于 assets，避免污染折旧汇总）
CREATE TABLE off_balance_registers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id),
    register_type VARCHAR(20) NOT NULL CHECK (register_type IN ('金租直租','售后回租','转售')),
    leasing_process_id UUID REFERENCES leasing_processes(id),
    start_date DATE,
    end_date DATE,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_obr_device ON off_balance_registers(device_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_obr_updated BEFORE UPDATE ON off_balance_registers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- device_stages：设备节点状态（一期 W3-4 设备粒度新路径，7 节点）。懒初始化；device.status 物化列由此派生
CREATE TABLE device_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id),
    stage VARCHAR(20) NOT NULL CHECK (stage IN ('订货','在途','到货','己方压测','上架','客户压测','点亮验收')),
    seq INTEGER NOT NULL CHECK (seq BETWEEN 1 AND 7),
    status VARCHAR(20) NOT NULL DEFAULT '未开始' CHECK (status IN ('未开始','进行中','已完成','不合格')),
    planned_date DATE,
    actual_date DATE,
    attachment_path VARCHAR(500),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_device_stages_device ON device_stages(device_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_device_stages_updated BEFORE UPDATE ON device_stages FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 验收记录（v3.1 新增）
CREATE TABLE acceptance_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    acceptance_type VARCHAR(20) NOT NULL CHECK (acceptance_type IN ('采购验收','销售验收')),
    order_id UUID REFERENCES orders(id),
    sales_order_id UUID REFERENCES sales_orders(id),
    status VARCHAR(20) NOT NULL DEFAULT '待验收' CHECK (status IN ('待验收','验收中','已通过','已驳回')),
    inspector VARCHAR(100),
    acceptance_date DATE,
    quantity_accepted INTEGER NOT NULL DEFAULT 0 CHECK (quantity_accepted >= 0),
    quantity_rejected INTEGER NOT NULL DEFAULT 0 CHECK (quantity_rejected >= 0),
    rejection_reason TEXT,
    file_path VARCHAR(500),
    attachments JSONB,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (
        (acceptance_type = '采购验收' AND order_id IS NOT NULL) OR
        (acceptance_type = '销售验收' AND sales_order_id IS NOT NULL)
    )
);
CREATE TRIGGER trg_acceptance_records_updated BEFORE UPDATE ON acceptance_records FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_acc_project ON acceptance_records(project_id) WHERE deleted_at IS NULL;

-- billings：v3.1 order_id→nullable、+sales_order_id +confirmation_status、唯一索引重建
CREATE TABLE billings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    contract_id UUID NOT NULL REFERENCES contracts(id),
    order_id UUID REFERENCES orders(id),
    sales_order_id UUID REFERENCES sales_orders(id),
    device_id UUID REFERENCES devices(id),
    period_index INTEGER NOT NULL CHECK (period_index > 0),
    period_label VARCHAR(20) NOT NULL,
    billing_date DATE NOT NULL,
    days_in_period INTEGER NOT NULL CHECK (days_in_period > 0),
    amount DECIMAL(18,2) NOT NULL CHECK (amount >= 0),
    amount_ex_tax DECIMAL(18,2) NOT NULL CHECK (amount_ex_tax >= 0),
    tax_amount DECIMAL(18,2) NOT NULL CHECK (tax_amount >= 0),
    tax_rate NUMERIC(10,8) NOT NULL DEFAULT 0.13 CHECK (tax_rate BETWEEN 0 AND 1),
    status VARCHAR(20) NOT NULL DEFAULT '未开' CHECK (status IN ('未开','已开','已收款','已红冲')),
    confirmation_status VARCHAR(20) CHECK (confirmation_status IS NULL OR confirmation_status IN ('待确认','已确认','有争议')),
    invoice_id UUID REFERENCES invoices(id),
    capital_transaction_id UUID REFERENCES capital_transactions(id),
    idempotency_key VARCHAR(128),
    reversal_of_id UUID REFERENCES billings(id),
    -- 二期 W5-6：币种与计费日记账汇率（迁移 0012；NULL=人民币）
    currency_code VARCHAR(10),
    booked_rate DECIMAL(18,8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (amount = ROUND(amount_ex_tax + tax_amount, 2))
);
-- v3.2 W5-6：唯一索引迁 device 维度（H-1 漂移修复；旧 service 从不写 sales_order_id，旧索引实际未挡重复）
CREATE UNIQUE INDEX uq_billing_period ON billings(device_id, period_index) WHERE deleted_at IS NULL AND device_id IS NOT NULL;
CREATE UNIQUE INDEX uq_billing_idem ON billings(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_billing_contract ON billings(contract_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_billing_order ON billings(order_id) WHERE deleted_at IS NULL AND order_id IS NOT NULL;
CREATE INDEX idx_billing_device ON billings(device_id) WHERE deleted_at IS NULL AND device_id IS NOT NULL;
CREATE TRIGGER trg_billings_updated BEFORE UPDATE ON billings FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 客户算力服务确认单（v3.1 新增）
CREATE TABLE service_confirmations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    billing_id UUID NOT NULL UNIQUE REFERENCES billings(id),
    sales_order_id UUID NOT NULL REFERENCES sales_orders(id),
    period_label VARCHAR(20) NOT NULL,
    file_path VARCHAR(500),
    confirmed_by_customer VARCHAR(100),
    confirmed_at DATE,
    status VARCHAR(20) NOT NULL DEFAULT '待确认' CHECK (status IN ('待确认','已确认','有争议')),
    dispute_reason TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_service_confirmations_updated BEFORE UPDATE ON service_confirmations FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX idx_sc_sales_order ON service_confirmations(sales_order_id) WHERE deleted_at IS NULL;

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

-- v3.2 W5-6：一机一卡（device_id 部分唯一）+ operation_status；转固/运营分离（折旧字段放宽 nullable）
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    equipment_model_id UUID NOT NULL REFERENCES equipment_models(id),
    order_id UUID REFERENCES orders(id),
    device_id UUID REFERENCES devices(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_original_value DECIMAL(18,2) NOT NULL CHECK (unit_original_value >= 0),
    total_original_value DECIMAL(18,2) NOT NULL CHECK (total_original_value >= 0),
    residual_rate NUMERIC(10,8) NOT NULL DEFAULT 0.10 CHECK (residual_rate BETWEEN 0 AND 1),
    residual_value DECIMAL(18,2) CHECK (residual_value >= 0),
    depreciable_value DECIMAL(18,2) CHECK (depreciable_value >= 0),
    annual_depreciation DECIMAL(18,2) CHECK (annual_depreciation >= 0),
    monthly_depreciation DECIMAL(18,2) CHECK (monthly_depreciation >= 0),
    start_date DATE,
    end_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT '折旧中' CHECK (status IN ('折旧中','已提完')),
    operation_status VARCHAR(20) NOT NULL DEFAULT '已转固未运营' CHECK (operation_status IN ('已转固未运营','运营中','已处置')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_assets_project ON assets(project_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_assets_device ON assets(device_id) WHERE deleted_at IS NULL AND device_id IS NOT NULL;
CREATE TRIGGER trg_assets_updated BEFORE UPDATE ON assets FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 长期应付款（一期 W7-8 售后回租新增） ============================

-- long_term_payables：售后回租回租出售时确认的长期应付款（per-device 唯一）。
-- carrying/sale_gain_loss/original_end_date/paid_amount 为钩子位（只存值，不分录，二期 EBS）。
CREATE TABLE long_term_payables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    leasing_process_id UUID NOT NULL REFERENCES leasing_processes(id),
    device_id UUID NOT NULL REFERENCES devices(id),
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    principal_amount DECIMAL(18,2) NOT NULL CHECK (principal_amount >= 0),
    carrying_amount DECIMAL(18,2) CHECK (carrying_amount >= 0),
    sale_gain_loss DECIMAL(18,2),
    original_end_date DATE,
    paid_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    status VARCHAR(20) NOT NULL DEFAULT '已确认' CHECK (status IN ('已确认','部分偿还','已结清','已撤销')),
    confirm_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_ltp_device ON long_term_payables(device_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_ltp_process ON long_term_payables(leasing_process_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_ltp_updated BEFORE UPDATE ON long_term_payables FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 盈利测算（v3.1 新增） ============================

CREATE TABLE profit_scenarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    name VARCHAR(200) NOT NULL,
    params_json JSONB NOT NULL,
    result_json JSONB NOT NULL,
    is_actual BOOLEAN NOT NULL DEFAULT FALSE,
    calculated_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_ps_project ON profit_scenarios(project_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_profit_scenarios_updated BEFORE UPDATE ON profit_scenarios FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 审计与幂等（基础设施） ============================

-- audit_logs：v3.1 action CHECK 扩展（ACCEPT_APPROVE/RECONCILE等）
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    action VARCHAR(20) NOT NULL CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE','ACCEPT_APPROVE','RECONCILE','RECONCILE_REVOKE','SUPERSEDE_REVOKE','CONFIRM_UPLOAD','DISBURSE','CAPITAL_TXN','LIGHT_ON','ALLOCATE','ALLOCATE_RETURN','LEASEBACK_SALE','REVENUE_JUDGE','REVENUE_OVERRIDE')),
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

-- ============================ 互引用 FK（所有表创建完毕后添加） ============================
ALTER TABLE capital_transactions
    ADD CONSTRAINT fk_ct_invoice FOREIGN KEY (invoice_id) REFERENCES invoices(id);
ALTER TABLE invoices
    ADD CONSTRAINT fk_inv_billing FOREIGN KEY (billing_id) REFERENCES billings(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE invoices
    ADD CONSTRAINT fk_inv_purchase_order FOREIGN KEY (purchase_order_id) REFERENCES orders(id);

-- ============================ 向导式工作台（v3.2 新增） ============================

CREATE TABLE workflow_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    steps JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_workflow_templates_updated BEFORE UPDATE ON workflow_templates FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE project_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL UNIQUE REFERENCES projects(id),
    template_id UUID REFERENCES workflow_templates(id),
    steps JSONB NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT '进行中' CHECK (status IN ('进行中','已完成','已暂停')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_pw_project ON project_workflows(project_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_project_workflows_updated BEFORE UPDATE ON project_workflows FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE step_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_workflow_id UUID NOT NULL REFERENCES project_workflows(id),
    step_seq INTEGER NOT NULL,
    step_name VARCHAR(100) NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('complete','skip','manual_complete','infer')),
    operator_id UUID REFERENCES users(id),
    operated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    note TEXT
);
CREATE INDEX idx_sal_workflow ON step_audit_logs(project_workflow_id);

-- ============================ 应用内消息提醒（F1 新增） ============================
-- 持久化 alert_service.compute_alerts 结果，按活跃用户扇出；各用户 read_at 独立。仅应用内铃铛，不接邮件/企微。
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    kind VARCHAR(64) NOT NULL,
    ref_type VARCHAR(32),
    ref_id VARCHAR(64),
    title VARCHAR(120) NOT NULL,
    body VARCHAR(500) NOT NULL,
    level VARCHAR(16) NOT NULL DEFAULT '提示',
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_notif_user_read ON notifications(user_id, read_at) WHERE deleted_at IS NULL;
CREATE INDEX idx_notif_user_created ON notifications(user_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX idx_notif_ref ON notifications(kind, ref_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_notifications_updated BEFORE UPDATE ON notifications FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ EBS 接口 Mock（二期 W1-2 新增） ============================
-- 业财一体化出站基础：SIEGPU→EBS Mock（10 类业务域），entity_version 内容 hash 幂等。
-- 与 alembic 0010 双写一致；Mock 阶段仅出站，入站属期外里程碑。
-- 字段映射配置：SIEGPU 字段 ↔ EBS 字段 + 转换规则
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
);
CREATE UNIQUE INDEX idx_ebs_fm_entity_field ON ebs_field_mappings(entity_type, siegpu_field) WHERE deleted_at IS NULL;
CREATE INDEX idx_ebs_fm_entity ON ebs_field_mappings(entity_type) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_ebs_fm_updated BEFORE UPDATE ON ebs_field_mappings FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 同步日志：每次出站一行，entity_version 内容 hash 做幂等/乱序判定
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
);
CREATE INDEX idx_ebs_sl_entity_version ON ebs_sync_logs(entity_type, entity_id, entity_version);
CREATE INDEX idx_ebs_sl_entity_status ON ebs_sync_logs(entity_type, status, synced_at DESC);
CREATE INDEX idx_ebs_sl_retry ON ebs_sync_logs(status, retry_count) WHERE status = 'FAILED';
CREATE TRIGGER trg_ebs_sl_updated BEFORE UPDATE ON ebs_sync_logs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 币种与汇率（二期 W5-6 新增） ============================
-- 量纲铁律（docs/superpowers/specs/2026-08-12-w5-6-unit-dimension-table.md）：
-- rate 存 DECIMAL(18,8) 全精度（直接标价法：1 外币 = N 元人民币），永不 round；金额两位，仅「外币×率→人民币」q2。
-- 与 alembic 0012 双写一致。
-- 币种主数据：is_base=TRUE 即本币（人民币），全系统恰好一个（service 层守卫）
CREATE TABLE currencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(10) NOT NULL,
    name VARCHAR(50) NOT NULL,
    symbol VARCHAR(10),
    is_base BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_currencies_code ON currencies(code) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_currencies_updated BEFORE UPDATE ON currencies FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 汇率表：取值 = from/to + rate_type 下 effective_date <= 业务日的最近一条（最近不未来）
CREATE TABLE exchange_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_currency VARCHAR(10) NOT NULL,
    to_currency VARCHAR(10) NOT NULL,
    rate_type VARCHAR(20) NOT NULL DEFAULT '中间价',
    rate DECIMAL(18,8) NOT NULL CHECK (rate > 0),
    effective_date DATE NOT NULL,
    source VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_fx_rates_lookup ON exchange_rates(from_currency, to_currency, rate_type, effective_date DESC) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_fx_rates_updated BEFORE UPDATE ON exchange_rates FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 汇兑损益科目规则：场景 → EBS 总账科目码（W11-12 分摊/三期过账用，本阶段先建配置）
CREATE TABLE exchange_gain_loss_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario VARCHAR(50) NOT NULL,
    gl_account_code VARCHAR(50) NOT NULL,
    description VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_fxgl_scenario ON exchange_gain_loss_rules(scenario) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_fxgl_updated BEFORE UPDATE ON exchange_gain_loss_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 保险管理（二期 W7-8 新增） ============================
-- 设备粒度保单：运输险（在途触发）/财产险（点亮触发）；保费按设备价值占比分摊到 insurance_policy_devices。
-- 硬约束：保费仅「点亮前」可归集进资产原值（collected_at 留痕幂等）；点亮后一律长期待摊（不触动折旧）。
-- 与 alembic 0013 双写一致。
CREATE TABLE insurance_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    batch_id UUID REFERENCES orders(id),          -- 批次（运输险按批次）；单台财产险可空
    policy_type VARCHAR(20) NOT NULL CHECK (policy_type IN ('运输险','财产险')),
    policy_no VARCHAR(100),
    insurer_id UUID REFERENCES suppliers(id),      -- 保险公司（供应商主数据）
    insured_amount DECIMAL(18,2) CHECK (insured_amount IS NULL OR insured_amount >= 0),   -- 保额
    premium_rate NUMERIC(10,8) CHECK (premium_rate IS NULL OR premium_rate >= 0),          -- 费率（小数，如 0.001）
    premium_amount DECIMAL(18,2) CHECK (premium_amount IS NULL OR premium_amount >= 0),    -- 保费 = q2(保额×费率)
    start_date DATE,
    end_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT '待确认' CHECK (status IN ('待确认','已生效','理赔中','已到期','已退保')),
    trigger_event VARCHAR(20),                     -- 在途/点亮/手工
    cost_allocation VARCHAR(20) CHECK (cost_allocation IS NULL OR cost_allocation IN ('资产原值','长期待摊')),
    amortization_months INTEGER CHECK (amortization_months IS NULL OR amortization_months > 0),
    collected_at TIMESTAMPTZ,                      -- 保费归集进原值的时间（幂等守卫 + 留痕）
    claims JSONB,                                  -- 理赔登记列表 [{date,amount,description,by}]
    file_path VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_inspol_project ON insurance_policies(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_inspol_batch ON insurance_policies(batch_id) WHERE deleted_at IS NULL AND batch_id IS NOT NULL;
CREATE INDEX idx_inspol_status ON insurance_policies(status, end_date) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_inspol_updated BEFORE UPDATE ON insurance_policies FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 保单-设备分摊：保费按设备价值（purchase_value）占比逐台分摊，末台吃尾差保合计精确
CREATE TABLE insurance_policy_devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id UUID NOT NULL REFERENCES insurance_policies(id),
    device_id UUID NOT NULL REFERENCES devices(id),
    allocated_amount DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (allocated_amount >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_inspd_policy_device ON insurance_policy_devices(policy_id, device_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_inspd_device ON insurance_policy_devices(device_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_inspd_updated BEFORE UPDATE ON insurance_policy_devices FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 投保配置：险种默认费率/投保比例/承保人/费用归集口径（自动投保的输入）
CREATE TABLE insurance_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_type VARCHAR(20) NOT NULL CHECK (policy_type IN ('运输险','财产险')),
    default_rate NUMERIC(10,8) CHECK (default_rate IS NULL OR default_rate >= 0),
    insured_ratio NUMERIC(10,8) CHECK (insured_ratio IS NULL OR insured_ratio >= 0),  -- 投保比例（1=全额）
    insurer_id UUID REFERENCES suppliers(id),
    cost_allocation VARCHAR(20) CHECK (cost_allocation IS NULL OR cost_allocation IN ('资产原值','长期待摊')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_inscfg_type ON insurance_configs(policy_type) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_inscfg_updated BEFORE UPDATE ON insurance_configs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 合同深化 + 单据编号 + 金租规则（二期 W9-10 新增） ============================
-- 与 alembic 0014 双写一致。预付款按 D2 裁定复用 devices 字段（不建 prepayments 表）。
-- 合同变更：before/after 快照 + 原因；变更落合同即对未来计费生效（计费按周期现算，无预生成计划行）
CREATE TABLE contract_amendments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id UUID NOT NULL REFERENCES contracts(id),
    amendment_date DATE NOT NULL,
    change_type VARCHAR(30) NOT NULL,        -- 金额变更/月租变更/期限变更/其他
    before_json JSONB,
    after_json JSONB,
    reason TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_ctramend_contract ON contract_amendments(contract_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_ctramend_updated BEFORE UPDATE ON contract_amendments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 合同终止：落合同 status=已终止 + 终止记录留痕
CREATE TABLE contract_terminations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id UUID NOT NULL REFERENCES contracts(id),
    termination_date DATE NOT NULL,
    reason TEXT,
    settlement_note TEXT,                     -- 结算说明（尾款/违约金安排）
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_ctrterm_contract ON contract_terminations(contract_id) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_ctrterm_updated BEFORE UPDATE ON contract_terminations FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 单据编号规则：前缀+日期段+流水（device_sn 规则回迁一期硬编码 GPU-{yyyymm}-{seq5}，生成结果必须一致）
CREATE TABLE doc_number_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type VARCHAR(50) NOT NULL,            -- device_sn/contract_no/batch_no/payment_no…
    prefix VARCHAR(20) NOT NULL DEFAULT '',
    date_format VARCHAR(20),                  -- YYYYMM / YYYYMMDD / NULL=无日期段
    seq_digits INTEGER NOT NULL DEFAULT 5 CHECK (seq_digits BETWEEN 1 AND 10),
    current_period VARCHAR(20),               -- 当前日期段（跨段流水归零）
    last_seq INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_docnum_type ON doc_number_rules(doc_type) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_docnum_updated BEFORE UPDATE ON doc_number_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 金租规则参数表（键值；如放款阈值默认、审批链配置）
CREATE TABLE leasing_rule_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key VARCHAR(50) NOT NULL,
    rule_value VARCHAR(200) NOT NULL,
    description VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_leasing_rule_key ON leasing_rule_configs(rule_key) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_leasing_rule_updated BEFORE UPDATE ON leasing_rule_configs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 付款管控 + 通用审批 + 进项税（二期 W11-12 新增） ============================
-- 与 alembic 0015 双写一致。核销多对多：一笔流水 ↔ 多发票/多批次/多台设备（按金额逐台多行）。
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    biz_type VARCHAR(30) NOT NULL,          -- 项目立项/付款申请/预付款/预算调整/监管划转/合同变更/收入确认…
    biz_id UUID,
    title VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '待审批' CHECK (status IN ('待审批','已通过','已驳回')),
    level INTEGER NOT NULL DEFAULT 1,
    max_level INTEGER NOT NULL DEFAULT 1,   -- 多级扩展位（本期单级）
    submitted_by UUID REFERENCES users(id),
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    reject_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_approvals_biz ON approvals(biz_type, biz_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_approvals_status ON approvals(status) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_approvals_updated BEFORE UPDATE ON approvals FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE payment_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    contract_id UUID REFERENCES contracts(id),
    direction VARCHAR(4) NOT NULL DEFAULT 'OUT' CHECK (direction IN ('IN','OUT')),
    amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
    currency_code VARCHAR(10),
    reason TEXT,
    prepayment_offset DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK (prepayment_offset >= 0),
    status VARCHAR(20) NOT NULL DEFAULT '待审批' CHECK (status IN ('待审批','已批准','已驳回','已付款')),
    approval_id UUID REFERENCES approvals(id),
    capital_transaction_id UUID REFERENCES capital_transactions(id),
    requested_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_payreq_project ON payment_requests(project_id, status) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_payreq_updated BEFORE UPDATE ON payment_requests FOR EACH ROW EXECUTE FUNCTION set_updated_at();

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
);
CREATE INDEX idx_payset_txn ON payment_settlements(capital_transaction_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_payset_invoice ON payment_settlements(invoice_id) WHERE deleted_at IS NULL AND invoice_id IS NOT NULL;
CREATE INDEX idx_payset_device ON payment_settlements(device_id) WHERE deleted_at IS NULL AND device_id IS NOT NULL;
CREATE TRIGGER trg_payset_updated BEFORE UPDATE ON payment_settlements FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================ 完成：48 张表 ============================
-- [v2.0 19表] users, suppliers, customers, equipment_models, banks,
-- projects, contracts, leasing_processes, leasing_nodes,
-- capital_transactions, invoices, capital_allocations,
-- orders, delivery_stages, billings, repayments, assets,
-- audit_logs, idempotency_keys
-- [v3.1 +5表] sales_orders, acceptance_records, funding_replacements,
-- profit_scenarios, service_confirmations
-- [一期W1-2 +3表] devices, batch_devices, off_balance_registers
-- [二期W1-2 +2表] ebs_field_mappings, ebs_sync_logs
