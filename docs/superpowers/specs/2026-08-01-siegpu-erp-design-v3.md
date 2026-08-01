# SIEGPU 算力租赁 ERP 系统设计 v3.0（全链路优化）

> 日期：2026-08-01 | 状态：DRAFT v3.1（经现有代码对照审计修订） | 基于 [v2.0](./2026-07-30-siegpu-erp-design-v2.md) 全链路补齐
> 上一版：v2.0（19 表，已实现一期三核心 + 依赖全通 + 前端）
> 审计修订：v3.0 草稿经 3 个只读 agent 对照现有代码核验，发现 4 CRITICAL + 9 HIGH + 9 MEDIUM，修订汇总见 §0.5

---

## 0. v2.0 → v3.0 变更摘要

| # | 变更 | 说明 | 章节 |
|---|---|---|---|
| 1 | 新增 `sales_orders` 表 | 销售合同下的分批次履约清单，与采购 `orders` 并列 | §1.1 |
| 2 | 新增 `acceptance_records` 表 | 采购验收 + 销售验收，独立于交付阶段，支持上传验收单 | §1.2 |
| 3 | 新增 `funding_replacements` 表 | 银行流贷/自有资金垫付 → 金租放款置换的完整跟踪链 | §1.3 |
| 4 | 新增 `profit_scenarios` 表 | 盈利测算场景存储，测算 vs 实际对比 | §1.4 |
| 5 | 新增 `service_confirmations` 表 | 客户每月算力服务确认单，计费→确认→开票的门控 | §1.5 |
| 6 | 扩展 `billings` | +sales_order_id、+confirmation_status | §1.6 |
| 7 | 扩展 `invoices` | +billing_id、+purchase_order_id、+reconciled_*，升级为发票池 | §1.7 |
| 8 | 金租放款自动置换 | disbursement 时自动扫描未置换付款 → 生成归还流水 | §2.2 |
| 9 | 发票池状态机 | 销售（待开→已开→已回款→已核销）/ 采购（待收票→已收票→已核销→已付款） | §2.3 |
| 10 | 应收核销 | 发票 ↔ 资金流水匹配勾销，支持部分核销 | §2.4 |
| 11 | 完整 17 步 demo + 测试 | 端到端全链路验证 | §3.4-3.5 |

---

## 0.5 审计修订记录（2026-08-01，对照现有代码）

> **审计方法**：派 3 个只读 agent 分别核验【数据模型层】【Service 层】【架构横切层】，每条结论引用 `file:line`，并与 v2.0 契约（状态机 §3.5 / 幂等 §3.6 / 红冲 §3.7 / 权限 §4 / 单位 §1.6+附录 B / 错误码 §6.2）交叉比对。下表按严重级排序：**CRITICAL=不改无法落地，HIGH=会踩坑返工，MEDIUM=一致性/措辞**。各章节内以 `> ⚠️ 审计修订 [ID]` 就地标注。

| ID | 级别 | 问题 | 修订位置 |
|---|---|---|---|
| C1 | 🔴 | `capital_transactions.source_type` 的 DB CHECK（schema.sql:184）不含 §2.2 要写的 `归还流贷/归还自有`，写入必被 PG 拒；§1.7 只提加 `is_replaced` 未提改 CHECK | §1.7、§2.2 |
| C2 | 🔴 | `invoices.status` 的 CHECK（schema.sql:221）缺 `已回款/已核销/待收票`，发票池状态机无法落地；§1.8 只列加字段未提改 CHECK | §1.8、§2.3 |
| C3 | 🔴 | 新增 验收通过/核销/置换/客户确认 等敏感操作，但 `require_role`（deps.py:28）从未启用、所有端点只要登录；未补权限矩阵 | 新增 §6 |
| C4 | 🔴 | `audit_logs` 表存在但全项目零写入；schema.sql:375 action CHECK 不含"核销/验收通过"，新操作零留痕 | 新增 §7 |
| H1 | 🟡 | profit 命名/路径双不一致：§3.1 `calculate_from_project` vs 代码 `calculate_for_project`（profit_service.py:157）；§3.2 `/api/profit/calculate` vs 现实 `/api/reports/profit/calculate`(POST) | §3.1、§3.2 |
| H2 | 🟡 | profit 6 项硬编码设计债属实（60月/4%/opex/disbursement_date/不读 LeasingProcess/不读 tax_rate），"自动提取"名不副实；tax_rate 默认 6% vs Contract 13% 隐性 bug | §1.4、§3.2 |
| H3 | 🟡 | §2.4"发票↔流水逐笔核销"与现有 `invoice_service.reconciliation()`（聚合对账报表）同名易混 | §2.4 |
| H4 | 🟡 | 测试库走 schema.sql 不走 alembic（conftest.py:25），§4 Phase1 只提 autogenerate 不提改 schema.sql → 单测全红 | §4 Phase1 |
| H5 | 🟡 | 文件上传 ENTITY_MAP（files.py:20）只认 contracts/invoices，验收单/确认单上传必须扩字典 | §1.2、§1.5、§3 |
| H6 | 🟡 | §2.3 采购发票"已收票→已核销→已付款"逻辑倒置（核销按 §2.4 匹配付款流水，应在付款后） | §2.3 |
| H7 | 🟡 | §2.2 部分置换的 `is_replaced` 语义空洞：部分置换后原付款标 TRUE/FALSE 都丢信息 | §1.7、§2.2 |
| H8 | 🟡 | `billings` 唯一索引 `uq_billing_period(order_id, period_index)`（billing.py:16），order_id 改可空后索引语义要重设 | §1.6 |
| H9 | 🟡 | `funding_replacements` 是金额类记录，能否红冲/撤销未定义（置换错了怎么纠正） | §1.3、§2.2 |
| M1 | 🟢 | §3.1 文件组织与现状不符：Invoice 在 billing.py、Order 在 delivery.py、Contract 在 project.py；测试目录是 `app/tests/` | §3.1、§3.5 |
| M2 | 🟢 | `/profit` 页面已存在（ProfitView.vue 186 行），§3.3"新增"应为"扩展" | §3.3 |
| M3 | 🟢 | "重写发票池"会抹掉 InvoicesView.vue 现有 OCR 自动填表 + 三流对账 Tab | §3.3 |
| M4 | 🟢 | §1.3 表内多余列 `created_at`（与"通用列"前言重复） | §1.3 |
| M5 | 🟢 | §2.1 Step2"级联"在 DB 层无实现（parent_contract_id 无 ON DELETE CASCADE），靠 service 层 | §2.1 |
| M6 | 🟢 | §3.4 demo 缺金租融资金额（放款多少→置换多少未给数字） | §3.4 |
| M7 | 🟢 | §1.4 `profit_scenarios.params_json` 利率/税率单位未约定（须遵循附录 B：存小数） | §1.4 |
| M8 | 🟢 | §1.1 `total_monthly_rent` 计算列维护方式未说明 | §1.1 |
| M9 | 🟢 | §1.2 acceptance_records 条件约束（采购验收必填 order_id、销售验收必填 sales_order_id）须 service 层校验 | §1.2 |

> **PASS 项（无需改，供参考）**：orders 纯采购与 sales_orders 不冲突；delivery_stages 6 阶段含点亮、light_on 同事务生资产；leasing_processes 的 `actual_disbursement_amount/disbursement_date/annual_rate/term_periods` 字段齐备；通用基类 `UUIDPK+TimestampMixin+with_loader_criteria` 软删除可直接复用；projects.customer_id 存在，sales_orders 无需冗余；disburse 事务边界（service flush + endpoint commit）对置换扩展友好、幂等三重防护可复用；错误契约 `BusinessError{code,message,details}` 清晰统一。

---

## 1. 新增数据模型

> 所有新表均含通用列：`id UUID PK`、`created_at TIMESTAMPTZ`、`updated_at TIMESTAMPTZ`、`deleted_at TIMESTAMPTZ`。下只列业务字段。

### 1.1 `sales_orders` — 销售订单

销售合同下的分批次履约清单。1 个销售合同可有多个销售订单（按设备型号/批次拆分）。

| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| contract_id | UUID FK→contracts | 销售合同（type=SALES） |
| equipment_model_id | UUID FK→equipment_models | |
| quantity | INTEGER | 租赁台数 |
| monthly_rent_per_unit | DECIMAL(18,2) | 单台月租（含税） |
| total_monthly_rent | DECIMAL(18,2) | = quantity × monthly_rent_per_unit |
| start_date | DATE | 计划起租日 |
| end_date | DATE | 计划止租日 |
| status | VARCHAR(20) | CHECK IN (待交付, 执行中, 已终止, 已完成) |
| notes | TEXT | |

与 `orders`（采购订单）并列，命名区分清晰。

> ⚠️ 审计修订 [M8]：`total_monthly_rent = quantity × monthly_rent_per_unit` 为冗余计算列，须由 service 层在 quantity/月租变更时同步更新，或改用 PostgreSQL `GENERATED ALWAYS AS` 列由 DB 维护，避免两者不一致。

### 1.2 `acceptance_records` — 验收记录

独立于 `delivery_stages`，记录采购验收（我方验设备）和销售验收（客户签收）。

| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| acceptance_type | VARCHAR(20) | CHECK IN (采购验收, 销售验收) |
| order_id | UUID FK→orders, nullable | 采购验收关联 |
| sales_order_id | UUID FK→sales_orders, nullable | 销售验收关联 |
| status | VARCHAR(20) | CHECK IN (待验收, 验收中, 已通过, 已驳回) |
| inspector | VARCHAR(100) | 验收人 |
| acceptance_date | DATE | |
| quantity_accepted | INTEGER | 合格数量 |
| quantity_rejected | INTEGER | 不合格数量 |
| rejection_reason | TEXT | |
| file_path | VARCHAR(500) | 验收单扫描件（采购/销售都支持上传） |
| attachments | JSONB | 补充附件 |
| notes | TEXT | |

> ⚠️ 审计修订 [M9/H5]：① `acceptance_type` 与关联字段的条件约束（采购验收→`order_id` 必填、销售验收→`sales_order_id` 必填）DB 层难表达，**须由 acceptance_service 校验**并抛 `VALIDATION_ERROR`(422)；② `file_path` 上传复用 `POST /api/files/{entity}/{eid}/upload`，但**必须扩展 `files.py:20` 的 `ENTITY_MAP`** 加入 `acceptances`，否则上传 404。

### 1.3 `funding_replacements` — 资金置换记录

跟踪"先用银行流贷/自有资金垫付 → 金租放款后置换"的完整链路。

| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| leasing_process_id | UUID FK→leasing_processes | 置换来源（金租放款） |
| original_txn_id | UUID FK→capital_transactions | 被置换的原付款流水 |
| replacement_txn_id | UUID FK→capital_transactions | 置换生成的归还流水 |
| amount | DECIMAL(18,2) | 置换金额 |
| source_type_replaced | VARCHAR(20) | 被置换的资金类型（银行流贷/自有资金） |
| replacement_date | DATE | 置换日期（=金租放款日） |
| status | VARCHAR(20) | CHECK IN (已置换, 已撤销) |

> ⚠️ 审计修订 [M4/H9]：① 删除原表内多余的 `created_at` 行（通用列 `UUIDPK+TimestampMixin` 已含 id/created_at/updated_at/deleted_at，新表照此继承）；② `funding_replacements` 属金额类财务记录，**置换出错时不可直接改金额**，须按 v2.0 §3.7 红冲范式处理：原置换记录置 `status=已撤销`、对其 `replacement_txn_id` 归还流水做红冲（反向 capital_transaction）、复原原付款的 `is_replaced/replaced_amount`。撤销动作进 audit_logs（§7）。

### 1.4 `profit_scenarios` — 盈利测算场景

| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| name | VARCHAR(200) | 场景名（如"基准方案"/"利率+1%压力测试"） |
| params_json | JSONB | 测算参数快照 |
| result_json | JSONB | 计算结果（月度明细+汇总指标） |
| is_actual | BOOLEAN DEFAULT FALSE | TRUE=从系统实际数据自动提取 |
| calculated_at | TIMESTAMPTZ | |
| created_by | UUID FK→users | |

> ⚠️ 审计修订 [M7/H2]：① `params_json` 内的利率/税率/残值率**必须存小数**（遵循 v2.0 附录 B：年利率 4% 存 `0.04`、税率 13% 存 `0.13`，禁止百分数直填）；② `is_actual=TRUE` 的"自动提取"现状名不副实——`profit_service.calculate_for_project` 只读 `Contract.amount/monthly_rent`，期限(60月)/利率(4%)/opex/disbursement_date 全硬编码、不读 `LeasingProcess` 实际融资参数、税率默认 6%（与 Contract 默认 13% 不符）。**本期须补：calculate 入参从 `LeasingProcess` 读 annual_rate/term_periods/payment_freq/actual_disbursement_amount/disbursement_date、从 `Contract` 读 tax_rate**，否则 is_actual 无意义（详见 §3.2）。

### 1.5 `service_confirmations` — 客户算力服务确认单

计费→开票之间的客户确认门控环节。

| 字段 | 类型 | 说明 |
|---|---|---|
| billing_id | UUID FK→billings, UNIQUE | 关联计费记录（1:1） |
| sales_order_id | UUID FK→sales_orders | |
| period_label | VARCHAR(20) | 如"2026-07" |
| file_path | VARCHAR(500) | 客户签字的确认单扫描件 |
| confirmed_by_customer | VARCHAR(100) | 客户方签字人 |
| confirmed_at | DATE | 客户确认日期 |
| status | VARCHAR(20) | CHECK IN (待确认, 已确认, 有争议) |
| dispute_reason | TEXT | 争议原因 |
| created_by | UUID FK→users | 我方提交人 |

> ⚠️ 审计修订 [H5]：`file_path` 上传同样须把 `confirmations` 加入 `files.py:20` 的 `ENTITY_MAP`（与 §1.2 验收单同批扩展）。

### 1.6 `billings` 扩展字段

| 新增字段 | 类型 | 说明 |
|---|---|---|
| sales_order_id | UUID FK→sales_orders | 关联销售订单（计费主关联源） |
| confirmation_status | VARCHAR(20) | 待确认 / 已确认 / 有争议（冗余，方便查询） |

> `order_id`（原采购订单关联）保留但改为可空冗余列，用于追溯设备来源。
>
> ⚠️ 审计修订 [H8]：现状 `billings` 唯一索引 `uq_billing_period(order_id, period_index)`（billing.py:16）以 `order_id` 为键。order_id 改可空 + sales_order_id 成主关联源后，**须重建唯一索引为 `(sales_order_id, period_index)`**（防同销售订单同期重复计费）；order_id 既可空，不能再作唯一键成员。另：`billing_service.generate_billing` 现以 `order_id` 为必填参数查点亮日（`_light_on_date`），若计费主关联切到 sales_order，**计费起点查找逻辑要同步改**，回归风险点须盯紧（§5）。

### 1.7 `capital_transactions` 扩展字段

| 新增字段 | 类型 | 说明 |
|---|---|---|
| is_replaced | BOOLEAN DEFAULT FALSE | 该笔付款是否已被金租放款**全额**置换 |
| replaced_amount | DECIMAL(18,2) DEFAULT 0 | 已置换金额累计（支持部分置换，见 §2.2） |

> ⚠️ 审计修订 [C1 阻断 / H7]：
> **[C1]** 现有 `source_type` 的 DB CHECK（schema.sql:184）白名单为 `自有资金/银行流贷/金租融资/租金收入/调配/调配归还/还款`，**不含 §2.2 要写的 `归还流贷/归还自有`**。迁移必须 `DROP CONSTRAINT ... ADD CONSTRAINT ...` 把这两个值加进白名单，否则归还流水写入被 PG 拒。（备选：复用现有 `还款` + 新增 `category` 区分，免改 CHECK。）
> **[H7]** 原设计单个 `is_replaced` 布尔无法表达"部分置换"。改为 `is_replaced`=**全额**标志 + `replaced_amount` 累计额：部分置换时 `replaced_amount += 本次额` 且 `is_replaced` 保持 FALSE；累计达原付款金额才置 TRUE。下次放款扫描条件改为 `is_replaced=FALSE AND replaced_amount < amount`。详见 §2.2。

### 1.8 `invoices` 扩展字段（发票池升级）

| 新增字段 | 类型 | 说明 |
|---|---|---|
| billing_id | UUID FK→billings, nullable | 关联计费（销售发票回填） |
| purchase_order_id | UUID FK→orders, nullable | 关联采购订单（采购发票） |
| reconciled_at | DATE, nullable | 核销完成日期 |
| reconciled_by | UUID FK→users, nullable | 核销人 |
| reconciliation_note | TEXT | 核销备注 |

> ⚠️ 审计修订 [C2 阻断]：现有 `invoices.status` 的 DB CHECK（schema.sql:221）为 `('待开','已开','已收票','已付款','已红冲')`，**不含 §2.3 发票池要用的 `待收票/已回款/已核销`**。迁移必须同步扩展该 CHECK，否则状态机迁移被 PG 拒。§2.3 是**对 v2.0 §3.5 状态机的修订**（v2.0 的 `待开→已开→已收票/已付款` 被 replaced），须同步更新 service 层 `assert_transition` 合法迁移表。
>
> 另：`Invoice` 模型实际定义在 `backend/app/models/billing.py`（与 `Billing` 同文件），**不存在 `invoice.py`**；§3.1 文件清单已据实修正（M1）。

---

## 2. 业务全流程（17 步）

### 2.1 完整端到端流程

```
Step  1  项目建立              projects
Step  2  多子合同建立           sales合同(parent) → purchase子合同(级联)
Step  3  销售订单               sales_orders(按批次/设备拆分)
Step  4  采购订单               orders(关联purchase合同)
Step  5  银行贷款入金           capital_transactions(source_type=银行流贷, IN)
Step  6  自有资金入金           capital_transactions(source_type=自有资金, IN)
Step  7  预付采购款             capital_transactions(OUT, 银行流贷+自有资金)
Step  8  金租申请+9节点推进     leasing_processes + leasing_nodes
Step  9  金租放款+自动置换      放款IN → 自动扫描未置换付款 → 生成归还流水
Step 10  采购验收               acceptance_records(type=采购验收) + 上传验收单
Step 11  到货/压测/运输/上架    delivery_stages(6阶段)
Step 12  销售验收               acceptance_records(type=销售验收) + 上传客户签字单
Step 13  点亮                   delivery_stages(点亮) → 同事务生成 assets
Step 14  计费                   billings(按月，关联sales_order) + 首月按天比例
Step 15  客户确认               service_confirmations(上传确认单) → billings可开票
Step 16  开票+回款+核销         invoices → 回款(IN) → 应收核销(发票↔流水匹配)
Step 17  盈利测算               系统数据自动提取 → 测算 vs 实际对比
```

> ⚠️ 审计修订 [M5]：Step 2"级联"指**应用层级联**——`contracts.parent_contract_id` 是自引用 FK 但**无 `ON DELETE CASCADE`**（schema.sql:122），父子合同联动（建销售合同时自动建采购子合同）须在 contract_service 内实现，非 DB 层。

### 2.2 金租放款自动置换逻辑（Step 9）

`leasing_service.disburse()` 扩展：

```
1. 放款入金 IN（source_type=金租融资，金额=actual_disbursement_amount）
2. 扫描该项目下 source_type IN (银行流贷, 自有资金)
   + direction=OUT + is_replaced=FALSE + replaced_amount < amount 的付款流水
3. 按付款时间升序匹配：
   FOR EACH 待置换付款流水（按时间从早到晚）：
     待置换额 = 付款金额 - replaced_amount
     IF 剩余放款额 >= 待置换额：本次置换额 = 待置换额（全额置换该笔剩余）
     ELSE IF 剩余放款额 > 0：本次置换额 = 剩余放款额（部分置换）
     ELSE：BREAK
     生成 funding_replacements（amount=本次置换额）
     生成 capital_transactions(IN, source_type=归还流贷/归还自有, amount=本次置换额)
     原付款 replaced_amount += 本次置换额
     IF replaced_amount >= 付款金额：原付款 is_replaced=TRUE
     剩余放款额 -= 本次置换额
4. 剩余放款额（>0）留作项目可用余额（不另开流水，由资金池余额反映）
```

> ⚠️ 审计修订 [C1/H7/H9/幂等/返回值]：
> - **[C1]** 第 3 步 `source_type=归还流贷/归还自有` 必须先扩 `capital_transactions.source_type` 的 CHECK（见 §1.7），否则写入被 PG 拒。
> - **[H7]** 用 `replaced_amount` 累计额替代单个布尔，正确处理部分置换：扫表条件 `is_replaced=FALSE AND replaced_amount < amount`；每笔按 `min(amount - replaced_amount, 剩余放款额)` 取本次置换额。
> - **[幂等]** disburse 本身三重防护（`SELECT FOR UPDATE` + `plan_generated/已放款` 守卫 + `idempotency_key=disburse:{id}`，leasing_service.py:94-110）保证放款只成功一次，置换随之幂等。`funding_replacements` 仍建议加唯一约束 `(original_txn_id, replacement_txn_id)` 防异常重试。
> - **[H9]** 置换出错按 §1.3 撤销范式（红冲归还流水 + 复原 is_replaced/replaced_amount + status=已撤销）。
> - **[返回值]** 现 disburse 返回 `(proc, txn, n)` 三元组（leasing_service.py:133）；扩展后若增返置换记录数，端点 leasing.py:81-85 响应体须向后兼容（§5）。

### 2.3 发票池状态机

**销售发票（direction=RECEIVABLE，我方开出）**：
```
待开 → 已开 → 已回款 → 已核销
  ↓              ↓
已红冲          已红冲
```

**采购发票（direction=PAYABLE，供应商开来）**：
```
待收票 → 已收票 → 已付款 → 已核销
   ↓                ↓
 已红冲           已红冲
```

> ⚠️ 审计修订 [C2/H6]：
> - **[C2]** 上述 `已回款/已核销/待收票` 是新增状态，须扩 `invoices.status` 的 CHECK（schema.sql:221，见 §1.8），并同步更新 service 层 `assert_transition` 合法迁移表。**本节即 v2.0 §3.5 发票状态机部分的替代定义**（v2.0 的 `待开→已开→已收票/已付款` 被 replaced）。
> - **[H6]** 采购发票状态机已修正为 `已收票→已付款→已核销`（原草稿"已核销→已付款"倒置）：核销按 §2.4 是"发票↔付款流水逐笔勾销"，须在付款（direction=OUT 流水）发生之后才能核销，故核销在已付款之后。

### 2.4 应收核销规则

核销 = 发票 ↔ 资金流水的匹配勾销：

- 销售发票：匹配 `capital_transactions(source_type=租金收入, direction=IN)`，按 contract_id 关联
- 采购发票：匹配 `capital_transactions(direction=OUT)` 中关联该合同的付款
- 支持部分核销（一张发票可多次收款），全部匹配后 `reconciled_at` 置日期
- 前端核销页：左列未核销发票，右列未匹配流水，勾选匹配 → 后端校验金额一致

---

## 3. API、Service、前端

### 3.1 后端文件清单

```
backend/app/
├── models/
│   ├── sales_order.py           # SalesOrder
│   ├── acceptance.py            # AcceptanceRecord
│   ├── funding.py               # FundingReplacement
│   ├── profit_scenario.py       # ProfitScenario
│   ├── service_confirmation.py  # ServiceConfirmation
│   ├── billing.py               # 扩展字段
│   └── invoice.py               # 扩展字段
├── schemas/
│   ├── sales_order.py
│   ├── acceptance.py
│   ├── funding.py
│   ├── profit.py
│   └── confirmation.py
├── services/
│   ├── sales_order_service.py
│   ├── acceptance_service.py
│   ├── funding_service.py       # 置换自动化引擎
│   ├── profit_service.py        # 扩展：calculate_from_project / compare
│   ├── confirmation_service.py
│   ├── invoice_service.py       # 扩展：reconcile / 核销
│   └── leasing_service.py       # 扩展：disburse() 内触发置换
├── api/v1/endpoints/
│   ├── sales_orders.py
│   ├── acceptances.py
│   ├── funding.py
│   ├── profit.py
│   ├── confirmations.py
│   └── invoices.py              # 扩展：pool / reconcile
```

> ⚠️ 审计修订 [M1]：上表"扩展"列的文件名须对齐现状——**`Invoice` 实际定义在 `models/billing.py`（与 `Billing` 同文件），不存在 `invoice.py`**；同理 `Order` 在 `models/delivery.py`、`Contract` 在 `models/project.py`。新增 5 个 model 须在 `models/__init__.py` 注册，否则 alembic autogenerate 检测不到。schemas/services/endpoints 按现有"按业务域聚合"组织即可，不必一模型一文件。

### 3.2 核心 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/sales-orders` | 创建销售订单 |
| GET | `/api/sales-orders?project_id=` | 按项目查询 |
| POST | `/api/acceptances` | 创建验收 + 上传验收单 |
| PUT | `/api/acceptances/{id}/approve` | 验收通过 |
| PUT | `/api/acceptances/{id}/reject` | 验收驳回 |
| GET | `/api/funding/replacements?project_id=` | 查询置换记录 |
| POST | `/api/leasing/{id}/disburse` | 放款（扩展：自动置换） |
| POST | `/api/confirmations` | 上传客户确认单 |
| GET | `/api/invoices/pool` | 发票池统一查询 |
| POST | `/api/invoices/{id}/reconcile` | 应收/应付核销 |
| GET | `/api/profit/calculate?project_id=` | 自动测算 |
| POST | `/api/profit/scenarios` | 保存测算场景 |
| GET | `/api/profit/compare?project_id=` | 测算 vs 实际对比 |

> ⚠️ 审计修订 [H1/H2/错误契约]：
>
> - **[H1 路径/命名]** 现 profit 走 `reports` 路由：`POST /api/reports/profit/calculate`、`GET /api/reports/profit/{project_id}`（reports.py:28-35），**不存在 `/api/profit/*`**；service 函数叫 `calculate_for_project`（profit_service.py:157），**不是 §3.1 写的 `calculate_from_project`**。决策二选一：(a) 新增独立 `/api/profit/*` 路由 + 保留旧 `/api/reports/profit/*`（前端 ProfitView.vue:80 现调 `/reports/profit/*`，须同步迁移）；(b) 沿用 `/api/reports/profit/*` 扩展 scenarios/compare。**推荐 (b)**，避免双路由。无论哪种，§3.1/§3.2 命名统一为 `calculate_for_project`。
> - **[H2 自动提取]** "自动测算"现状是假象——`calculate_for_project` 只读 `Contract.amount/monthly_rent`，期限/利率/opex/disbursement_date 全硬编码、不读 `LeasingProcess`、税率默认 6%（Contract 实际 13%）。本期必须补：入参从 `LeasingProcess` 读 annual_rate/term_periods/payment_freq/actual_disbursement_amount/disbursement_date、从 `Contract` 读 tax_rate，并修 tax_rate 默认值 bug。
> - **[错误契约]** 现 `calculate_for_project` 出错返 `{"error":...}`(200)（profit_service.py:161,167），违反项目 `BusinessError` 契约。顺手改为 `raise BusinessError("NOT_FOUND","项目不存在",404)` / `BAD_REQUEST`，统一 v2.0 §6.2 错误码体系。

### 3.3 前端页面

| 页面 | 路由 | 类型 | 说明 |
|---|---|---|---|
| 销售订单 | `/sales-orders` | 新增 | GenericCrud + 项目筛选 |
| 验收管理 | `/acceptances` | 新增 | 采购/销售双Tab + 上传 |
| 发票池 | `/invoices` | 扩展（**保留**现有 OCR + 三流对账） | 收/付双Tab + 状态流转 + 核销 |
| 客户确认 | `/confirmations` | 新增 | 待确认列表 + 上传确认单 |
| 盈利测算 | `/profit` | **扩展**（ProfitView.vue 已存在 186 行） | 加场景保存/对比，对接 scenarios、compare |
| 资金池 | `/capital` | 扩展 | 增加置换记录展示 |
| 金租流程 | `/leasing` | 扩展 | 放款后展示置换结果 |

> ⚠️ 审计修订 [M2/M3]：
>
> - **[M2]** `/profit` 页面**已存在**（ProfitView.vue 186 行，router/index.ts:17 已注册，MainLayout.vue:28 侧边栏已含），本版是**扩展**不是新增——加 profit_scenarios 保存 + 测算 vs 实际对比图表。
> - **[M3]** `/invoices` 已是 178 行的 InvoicesView.vue，含 OCR 自动填表（`/api/ocr/invoice`）+ 三流对账 Tab（`/invoices/reconciliation`），"重写"**必须保留**这两项，只在原页加状态流转 + 核销交互。
> - 新增"销售订单/验收/确认"页：销售订单可走 GenericCrud（`master/:module` 通配路由 + modules.ts 配置项）；验收/确认带状态机和上传，应仿 InvoicesView 走独立 .vue（GenericCrud 不适合状态机页面）。

### 3.4 Demo 脚本

`demo.py` 按 17 步全流程重写，使用真实测算表数据（商机5090：1372台，采购不含税≈7.35亿，含税≈8.30亿，月租含税≈2167.76万，金租4%/60月等额本息）：

1. 主数据（客户/供应商/设备/银行）
2. 销售合同 + 采购子合同（级联）
3. 销售订单
4. 采购订单（1372台）
5. 银行流贷 IN（70%）
6. 自有资金 IN（30%）
7. 预付采购款 OUT（流贷+自有）
8. 金租申请 + 推进9节点
9. 金租放款 + 自动置换（归还流贷+自有）
10. 采购验收 + 上传验收单
11. 交付6阶段推进
12. 销售验收 + 上传验收单
13. 点亮 + 资产生成
14. 计费（3个月：首月整月 + 2个月）
15. 客户确认（上传确认单）
16. 开票 + 回款 + 核销
17. 盈利测算 vs 实际对比

幂等：项目 code `DEMO-5090` 已存在则跳过。

> ⚠️ 审计修订 [M6/C1]：① 须补**金租融资金额**（actual_disbursement_amount）——demo 只给了采购含税 8.30亿、月租、4%/60月，但 Step 9 放款多少→置换多少未给数字，应明确（如"金租融资 8.30亿，全额置换前期流贷+自有垫付"）；② Step 9 置换生成的归还流水 `source_type=归还流贷/归还自有` 须先扩 CHECK（C1，§1.7），否则 demo 跑到 Step 9 即抛 `ConstraintViolationError`。

### 3.5 测试策略

| 层 | 内容 | 目标 |
|---|---|---|
| 单元测试 | 置换算法 / 核销匹配 / 盈利计算 / 状态机校验 | 新增 15+ 用例 |
| 集成测试 | 全链路 17 步 pytest 脚本 | 1 个全流程 |
| E2E | 发票池核销 / 盈利测算页 / 验收上传 | 新增 3 个 spec |

> ⚠️ 审计修订 [M1/测试基建]：
>
> - ① 单测目录是 **`backend/app/tests/`**（非 `backend/tests/`），fixture 在 `conftest.py`（session 级建 `siegpu_test` 库 + 每用例事务回滚隔离），新测按模块分文件（如 `test_funding_service.py`、`test_acceptance_service.py`）。
> - ② "全流程 17 步集成测试"无先例（现有都是"单 service + 真实 PG"中粒度），建议放 `app/tests/test_full_flow.py`。
> - ③ E2E 框架在**仓库根 `e2e/`（Playwright）**已存在（非 frontend 下），新增 3 spec 加到 `e2e/` 目录。
> - ④ 测试库走 `schema.sql` 建表（见 H4），新表/新列不改 schema.sql → 所有单测建表失败。

---

## 4. 执行计划

### Phase 1：数据层（models + 迁移）
- 新建 5 个 model 文件 + 扩展 3 个现有模型（Billing / CapitalTransaction / Invoice，都在各自现有文件内改——Invoice 在 billing.py、CapitalTransaction 在 capital.py，非新文件）
- 新模型在 `models/__init__.py` 注册（否则 autogenerate 检测不到）
- 写 schema（Pydantic）

> ⚠️ 审计修订 [H4/C1/C2 双源铁律]：本项目有**两个 DDL 真相源**——生产走 alembic 迁移、测试库（conftest.py:25）直接读 `db/schema.sql`。**新表/新列必须同时改两处**，否则单测建表失败：
>
> - 改 `db/schema.sql`：加 5 张新表 DDL + 给 capital_transactions/invoices/billings 加新列 + **扩 3 个 CHECK**（capital_transactions.source_type 加 `归还流贷/归还自有`[C1]、invoices.status 加 `待收票/已回款/已核销`[C2]、audit_logs.action 加 `RECONCILE/ACCEPT_APPROVE` 等[C4]）+ 重建 billings 唯一索引为 `(sales_order_id, period_index)`[H8] + capital_transactions 加 `replaced_amount` 列[H7]
> - 写 alembic 增量迁移（`alembic revision --autogenerate`，本项目**首条增量迁移**、无先例，生成后须人工核对）
> - **autogenerate 不会检测 CHECK 内容变更和索引重命名，这两类须手写进迁移**（DROP CONSTRAINT ... ADD CONSTRAINT ...）

### Phase 2：Service 层
- sales_order / acceptance / funding（置换引擎）/ confirmation / profit 扩展
- invoice_service 扩展（核销逻辑）
- leasing_service 扩展（放款触发置换）

### Phase 3：API 层
- 新增 6 个 endpoint 文件 + 扩展 2 个
- 注册路由

### Phase 4：Demo + 测试
- 重写 demo.py（17 步）
- 新增 15+ 单元测试
- 新增 1 个全流程集成测试
- 新增 3 个 E2E spec

### Phase 5：前端
- 新增 3 个页面（销售订单/验收/确认）
- 重写 1 个页面（发票池）
- 新增 1 个页面（盈利测算）
- 扩展 2 个页面（资金池/金租）

### Phase 6：端到端验证
- docker compose up 运行全链路
- 验证 17 步 demo
- 跑全部测试（pytest + Playwright）
- 确保 0 回归

---

## 5. 向后兼容

- 现有 19 张表不删除、不改名、不改已有列类型（仅扩 CHECK 白名单、加可空列、重建 billings 唯一索引）
- 现有 61 个单测保持全绿（新表/新列同步改 schema.sql 是前提，见 §4 H4）
- `billings.order_id` 保留为可空冗余列，唯一索引迁到 `(sales_order_id, period_index)`[H8]
- 新增服务遵循现有 `service flush + endpoint commit` 分层 + `raise BusinessError` 错误契约（profit 旧的 `return {"error":...}` 顺手改掉）
- `leasing_service.disburse()` 返回值保持 `(proc, txn, n)` 三元组向后兼容，置换记录数走新字段或新端点
- 前端新增页面追加到侧边栏；`/invoices` 重写须保留 OCR + 三流对账[M3]，`/profit` 为扩展非新增[M2]
- 文件上传复用 `/api/files/{entity}/{eid}/upload`，仅扩 `ENTITY_MAP`（加 acceptances/confirmations）[H5]

> ⚠️ 最易破坏现状的 3 处须重点回归：① 计费主关联从 order_id 切到 sales_order_id（触及 `_light_on_date` 点亮日查询）；② 发票状态机重写（须兼容 mark_paid 现有调用 leasing.py/invoices.py）；③ disburse 内嵌置换逻辑（须保持原返回值契约）。

---

## 6. 权限矩阵补充（角色 × v3.0 新增操作）

> ⚠️ 审计修订 [C3]：v2.0 §4 权限矩阵未覆盖 v3.0 新增操作；更严重的是 `require_role`（core/deps.py:28）**定义后从未被任何端点调用**——所有现有端点（含红冲/放款/删除）只要登录即可操作。v3.0 新增的敏感财务操作必须启用 `require_role` 做路由级 + service 级双重校验。角色：ADMIN（超管全权）/ FINANCE_DIRECTOR（财务总监）/ PROCUREMENT（采购对接人）/ DELIVERY（项目交付）/ FINANCE_STAFF（财务专员）。V=查看 C=新增 E=编辑 A=审批。

| v3.0 新增模块/操作 | ADMIN | FINANCE_DIRECTOR | PROCUREMENT | DELIVERY | FINANCE_STAFF |
|---|---|---|---|---|---|
| 销售订单（sales_orders） | VCE | VCE | V | V | V |
| 验收记录 查看/创建 | VCE | VCE | VC（采购验收） | VC（销售验收） | V |
| 验收通过/驳回（approve/reject） | A | A | · | · | · |
| 资金置换 查看 | V | V | V | V | V |
| 金租放款（含自动置换） | A | A | · | · | · |
| 客户确认单 上传/查看 | VCE | VCE | · | VC | V |
| 计费（billings）生成 | VCE | VCE | · | V | VCE |
| 发票核销（reconcile_invoice_to_txn） | A | A | · | · | VC（发起，待 A） |
| 发票红冲审批 | A | A | · | · | · |
| 盈利测算 查看/保存场景 | VC | VC | V | V | VC |
| funding_replacements 撤销 | A | A | · | · | · |

> **实现要求**：① A（审批）类端点必须 `Depends(require_role("ADMIN","FINANCE_DIRECTOR"))`；② service 层对审批动作二次校验角色（防端点漏挂依赖）；③ 前端 `router/index.ts` 加角色守卫、`MainLayout.vue` 侧边栏按 `auth.role` 过滤（现状是固定 menuOptions，本期顺带修）。

---

## 7. 审计日志要求（audit_logs 写入）

> ⚠️ 审计修订 [C4]：`audit_logs` 表存在（schema.sql:372，append-only，应用 DB role 仅 INSERT/SELECT）但**全项目零写入**——连现有红冲/放款/资金记账都没留痕。v3.0 新增敏感财务操作必须补 `db.add(AuditLog(...))`。

**本期须写入 audit_logs 的动作**：

| action | 触发点 | 关键字段 |
|---|---|---|
| ACCEPT_APPROVE | 验收通过/驳回 | target=acceptance_id, after=status |
| SUPERSEDE | 金租放款触发置换 | target=funding_replacement_id, after=置换金额 |
| SUPERSEDE_REVOKE | 置换撤销（§1.3） | target=funding_replacement_id |
| RECONCILE | 发票核销（§2.4） | target=invoice_id, after=核销金额 |
| RECONCILE_REVOKE | 核销撤销 | target=invoice_id |
| CONFIRM_UPLOAD | 客户确认单上传 | target=confirmation_id |
| REVERSE | 红冲（发票/流水/置换归还流水，现有动作补写入） | target=原记录 id |

> **迁移要求**：`audit_logs.action` 的 CHECK（schema.sql:375）现为 `CREATE/UPDATE/DELETE/REVERSE/LOGIN/APPROVE_OVERCONTRACT/SUPERSEDE`，**不含 `ACCEPT_APPROVE/RECONCILE/RECONCILE_REVOKE/SUPERSEDE_REVOKE/CONFIRM_UPLOAD`**，必须扩该 CHECK，否则审计写入被 PG 拒。
>
> **写入位置**：在每个写操作 service 方法的事务内 `db.add(AuditLog(...))`（与业务记录同事务，保证原子）；`user_id` 取自 `get_current_user`，`before_json/after_json` 记录关键字段变更。

---

> 下一节：无。设计定稿后进入实现阶段（Phase 1-6）。
