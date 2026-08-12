# SIEGPU ERP 二期（业财一体化核心）详细执行计划书

> 日期：2026-08-10 | 版本：v1.2（裁定定稿） | 状态：**✅ 已授权开工 → W1-2 EBS Mock（债④ 先修）**
> 父计划：[`2026-08-04-siegpu-upgrade-plan.md`](./2026-08-04-siegpu-upgrade-plan.md) §3（V2.2，二期 12-14 周 / 原 16 新表〔D2 裁定后 15〕/ 6 阶段）
> 本文件职责：把父计划 §3 的"模块级设计"下沉到**逐周 / 逐文件 / 逐表 / 逐测试**的可执行粒度，并对二期部分做**针对现状（一期已完成）的批判性复审**，记录父计划写就时（2026-08-04，一期未完成）尚不存在的差异。

---

## 0. 假设明示（先看这里，便于事后校验）

以下 5 项是动笔前我无法从代码/文档单独裁定、按最稳妥默认推进的假设。**任一若与你的意图不符，请直接纠正，我会回改计划——这些都不应静默脑补。**

| # | 假设 | 依据 | 若不符的后果 |
|---|---|---|---|
| A1 | ✅ **已裁定（2026-08-10）：授权立即开工，从 W1-2 起。** | 用户拍板 | — |
| A2 | ✅ **已裁定：规则 R1 改用 `'经营租赁'`**（schema CHECK 不动，零迁移；原父计划文案 `算力经营租赁` 作废）。 | 用户拍板 D1；schema.sql:114 `IN ('经营租赁','转售','自营')` | — |
| A3 | ✅ **已裁定：现在就修债④**（同债③ waitForResponse 锚点手法，作为二期新 e2e 上线前的并发基线治理）。 | 用户拍板；与债③同类（共享慢库 + 并发） | — |
| A4 | **W11-12 过载，建议把 `doc_number_rules` / `leasing_rule_configs` 前移到 W9-10**（见 §5 重排）。 | W11-12 原 2 周塞 5 表 + 4 子域 | 不重排则 W11-12 滑期概率高 |
| A5 | **二期"收入判定"只产出判定结果快照（写合同），不驱动收入确认动作**（确认属三期 §4.2）。 | 父计划 §3.2 vs §4.2 分工 | 否则 W3-4 范围爆炸 |

---

## 1. 现状基线（2026-08-10 实测，非引用父计划旧数）

| 维度 | 父计划基线（2026-08-04） | 现状（一期完成后） | 变化 |
|---|---|---|---|
| 数据表 | 27 | **33** | +6（设备层 devices/batch_devices/device_stages/off_balance_registers/acceptance_records + 通知/审计等，一期增量） |
| pytest | 94 | **249**（29 个测试文件） | +155（一期设备层 + 金租回租 + 迁移 parity 等） |
| e2e | 24 用例 / 17 spec | **50 用例 / 24 spec** | +26 用例 / +7 spec（设备清单 / wizard-workspace / w5_6 / w7_8 / revenue-chain / 角色登录…） |
| alembic 迁移 | — | **9**（0001–0009） | 一期全程双写（迁移 + schema.sql + parity 测试） |
| 模型文件 | 17 | 21 | device / acceptance / notification / step_audit_log / 等 |

> **含义**：二期"新增 ≥35 pytest / 6 e2e"的基数已从父计划的 94/24 涨到 249/50。本计划统一以**现状**为基数表述"新增"，避免"新增"语义漂移（父计划 §0.4 基线已过期）。

---

## 2. 二期总览（沿用父计划 §3，重排见 §5）

| 阶段 | 工期 | 主题 | 新表 | 父计划章节 |
|---|---|---|---|---|
| W1-2 | 2 周 | EBS 接口 Mock 骨架（出站） | ebs_field_mappings / ebs_sync_logs | §3.1 |
| W3-4 | 2 周 | 收入核算路径判定引擎 | —（contracts +6 字段） | §3.2 |
| W5-6 | 2 周 | 币种与汇率管理 | currencies / exchange_rates / exchange_gain_loss_rules | §3.3 |
| W7-8 | 2 周 | 保险管理（设备粒度） | insurance_policies / insurance_policy_devices / insurance_configs | §3.4 |
| W9-10 | 2 周 | 合同深化 + 预付款结转 + 基础规则（重排后） | contract_amendments / contract_terminations / **doc_number_rules / leasing_rule_configs**〔预付款复用 devices 字段，无新表〕 | §3.5 + §3.6 末 |
| W11-12 | 2 周 | 付款三重管控 + 通用审批 + 进项侧（重排后） | approvals / payment_requests / payment_settlements | §3.6 |
| W13-14 | 2 周 | 全链联调 + golden 算例 + 端到端 | — | §3.6 联调 |
| | | **合计** | **15 新表**（父计划 §3.7 原 16，D2 裁定复用 devices 字段、不建 prepayments 表 → −1） | |

---

## 3. 批判性复审结论（针对现状，逐条已读码验证）

> 父计划经过 V1→V2 两轮独立审计（A1–A24 全处置），质量成熟。下列是**父计划写就时一期未完成、无法核对**的新差异，本复审首次发现。每条带"建议处置"。

### D1 ｜HIGH｜收入判定 R1 的 business_type 取值不在 schema 枚举内（硬阻塞 W3-4）

- **现状**：`schema.sql:114` `business_type VARCHAR(20) CHECK (business_type IS NULL OR business_type IN ('经营租赁','转售','自营'))`；`project.py:23` 注释亦为"经营租赁/转售/自营"。
- **父计划 §3.2 R1**：`projects.business_type=="算力经营租赁" AND leasing_mode=="自有" AND 合同==SALES → 经营租赁`。
- **问题**：`算力经营租赁` 不在枚举里 → **R1 永不命中** → 自有设备出租（系统的主干营收场景）全部走 R4"待判定→人工"，判定引擎形同虚设。
- **建议处置**：W3-4 动工前由财务裁定——
  - 方案 a（推荐，改动小）：规则文案 `算力经营租赁` → `'经营租赁'`，与一期已落地的枚举对齐。
  - 方案 b：扩枚举加 `'算力经营租赁'`（需 alembic 迁移改 CHECK + 数据回填 + parity）。
  - 无论 a/b，必须在 `test_revenue_judge.py` 里用**真实枚举值**造数据断言 R1 命中（防文案/枚举再次漂移）。

### D2 ｜已裁定（2026-08-10）｜复用 devices 预付款字段，不新建 prepayments 表（二期 16→15 表）

- **现状**：`schema.sql:387/390` `devices.prepayment_amount` + `devices.prepayment_settled`（一期 W7-8 售后回租用，`w7_8_leaseback_disbursement.spec.ts` 覆盖）。
- **父计划 §3.5**：原拟 `prepayments` 作"全新模块"（合同级完整表）。
- **裁定（用户拍板）**：**不新建 `prepayments` 表**，复用 devices 字段作预付款单一真源（避免双源冲突）；二期只补「按月结转抵扣」service+规则——
  - devices 加一列 `prepayment_settled_amount`（累计已结转/抵扣额，nullable，W9-10 迁移 0011）；每月计费时 `prepayment_service` 按规则（比例/直线）算结转额，累加进该列，全额结转时置 `prepayment_settled=True`。
  - 一期既有 `prepayment_settled` 语义不变（售后回租 e2e 零回归）；新列对老行为纯加法（nullable 默认 0）。
  - 合同级预付款台账（前端 `PrepaymentView.vue`）改为聚合 devices 行，不落新表。
- **影响**：二期新表 16→**15**（去 prepayments）；`payment_settlements`（W11-12 付款核销）保留，但不再回写 prepayments，改为按需更新 devices 结转列。

### D3 ｜MEDIUM｜EBS Mock 的"字段映射"依赖财务按真实科目表评审（非纯技术阻塞）

- **现状**：无任何 EBS 相关表/代码（确认 15 表全无）。
- **父计划 §3.1**：W1 即"向 IT/EBS 申请接口规范 + 请财务评审字段映射"。
- **问题**：真实 EBS 规范属期外里程碑（§0.3），Mock 按假设字段建；等真规范来了映射要返工。
- **建议处置**：**不阻塞**——按父计划既定折中走（`EBS_MOCK_MODE` 切换、Mock 返回 `MOCK_SUCCESS`）；但 `ebs_field_mappings` 表设计要**泛化**（`transform_rule` DIRECT/FORMULA/LOOKUP + `transform_config` JSONB 已够灵活），W1 同步发接口规范申请函（走外部流程，不等）。在风险登记册标"映射返工概率中"。

### D4 ｜MEDIUM｜立项走 approvals 审批，会改变现有"直接建项目"流程（向后兼容点）

- **现状**：项目创建是直接 `POST /projects` 建实体 + `after_action`（workflow_service，try/except advisory only）；`wizard-workspace.spec.ts` 依赖直接建项目。
- **父计划 §3.6**：`approvals.biz_type` 加"项目立项"，单级审批落地。
- **问题**：给立项加审批门 = 改变建项目主流程，可能影响 wizard-workspace e2e 与现有"立项即用"体验。
- **建议处置**：W11-12 实现时**双轨**——审批为可选（`approvals` 存在则卡，不存在/旧项目则走原直接路径）；e2e 用 cfo 直接通过审批，零回归。与"立项多级审核本期单级"对齐。

### D5 ｜LOW｜收入判定 R1b"服务费逐月确认"在二期只判定不执行（防范围误扩）

- **现状**：一期计费（`billing_service.generate_billing` 按台）是"经营租赁月租"口径。
- **父计划 §3.2 R1b + §10.5**：转租赁收客户租金全额按服务费逐月确认（财务裁定 2026-08-04）。
- **问题**："按服务费确认收入"属**收入确认**（三期 §4.2 `revenue_recognitions`），≠ 二期计费。
- **建议处置**：W3-4 仅产出 `revenue_method` 判定结果快照（写合同 + 同步 EBS Mock），**不**实现服务费确认逻辑；在 W3-4 验收清单显式写"判定结果落库 + EBS Mock 出站 + 不驱动确认"。否则 W3-4 范围爆炸（A5）。

### D6 ｜LOW｜汇兑损益 / 保费摊销 / 设备分摊是"单位量纲重灾区"，须建全链路对照表

- **审计铁律**（`~/.claude/rules/workflow/audit-verification.md` §6-7）：混合单位系统（百分数/小数/含税/不含税/汇率）是 bug 重灾区，端到端测试要覆盖**往返闭环**用真值断言。
- **二期高危字段**：`invoice_rate` / `settlement_rate` / `booked_rate`（DECIMAL(18,8) 汇率）、汇兑损益 `amount × (invoice_rate − settlement_rate)`、保费 `insured_ratio` × 价值占比分摊、payment_settlements 按金额占比逐台分摊。
- **建议处置**：每个这类字段建**全链路对照表**（输入单位/存储单位/计算单位/输出单位/各转换点），作为 W5-6 / W7-8 / W11-12 的测试依据；golden 算例用真值追值法（参考 `revenue-chain.spec.ts` 的 B/I 追值模式）。

---

## 4. 横切铁律（每周执行时守）

- **schema 改动双写 + 可逆**：每张新表 = alembic 迁移（`0010_` 起）+ `schema.sql` 同步 + `test_migration_parity.py` 加 case；迁移必须 `downgrade` 可回滚（一期 9 个迁移全程如此）。
- **不破坏现有功能（规则3）**：contracts/invoices/billings/capital_transactions 一律**加 nullable 字段**，不改核心字段语义；新功能建新文件/新模块。
- **service 不 commit 铁律**：所有新 service 函数只 `flush`，commit 在 endpoint / scheduler。
- **端到端验证铁律**：每阶段除 pytest 外，至少 1 条 e2e 覆盖该阶段主干 UI 流；"后端跑通"不是完成线。
- **单位量纲**：金额/汇率字段必出全链路对照表 + golden 算例（D6）。
- **并发 flake 防范**：新 e2e 造数用 RUN 派生唯一数据 + `E2E-`/`GPU-` 前缀（globalTeardown 清）；定位"我的数据"用唯一锚点（SN / 合同号 / RUN），**禁用 `.first()` 首行假设**（债③教训）。
- **不 git commit**：未经用户授权不提交。

---

## 5. 逐周执行计划

> 每周统一结构：**目标 / 新表 DDL 要点 / 新文件 / 改动文件 / 算法要点 / 测试 / 验收门 / 依赖 / 风险**。

### W1-2 ｜ EBS 接口 Mock 骨架（出站）

- **目标**：搭 EBS HTTP Client（Mock 实现）+ 同步日志 + 字段映射配置 + 监控页；6 类业务域 10 个 sync 方法跑通 Mock 出站。
- **新表**：
  - `ebs_field_mappings`（entity_type / siegpu_field / ebs_field / transform_rule / transform_config JSONB）
  - `ebs_sync_logs`（entity_type / entity_id / **entity_version hash**（幂等/乱序，Mock 期养成）/ direction / sync_type / status / request_payload / response_payload / error_message / retry_count / synced_at）
- **新文件**：
  - `backend/app/services/ebs_client.py`（Mock HTTP client，`EBS_MOCK_MODE` 切换，返回 `{status:MOCK_SUCCESS, ebs_reference:MOCK-EBS-{uuid}}`）
  - `backend/app/services/ebs_sync_service.py`（10 个 sync 方法：customer/supplier/contract/invoice/asset/payment/prepayment/lease_disbursement/repayment/goods_receipt）
  - `backend/app/models/ebs.py`（两张表 ORM）
  - `backend/app/schemas/ebs.py`、`backend/app/api/v1/endpoints/ebs.py`（映射配置 CRUD + 日志查询 + 失败重试）
  - `frontend/src/views/EbsMonitor.vue`（映射配置编辑 / 日志查询 / 失败批量重试 / 同步统计）
- **改动文件**：`main.py`（注册 router）、`models/__init__.py`、前端路由 `router/index.ts`、`MainLayout.vue`（菜单项，cfo 可见）。
- **算法要点**：资产类 sync 到**单台设备级**；采购应付类支持**批次+单台行级**；融资核算类到项目/批次级。`entity_version` = 实体内容 hash，重复同步幂等跳过。
- **测试**：`test_ebs_sync.py`（≥6 条）—— 10 个 sync 方法各 1 条 Mock 成功 + `entity_version` 幂等（同内容二次 sync 不新建 log）+ 失败重试计数 + `EBS_MOCK_MODE=false` 分支。e2e 1 条（EbsMonitor 页映射配置编辑 + 触发一次 sync 看日志）。
- **验收门**：10 sync 方法 Mock 全绿；幂等正确；EbsMonitor 页可查日志。
- **依赖**：无（一期已有 customer/supplier/contract/invoice/asset/payment 主数据）。
- **风险**：字段映射返工（D3，已接受折中）。**W1 同步动作**：发 EBS 接口规范申请函（外部，不阻塞）。

### W3-4 ｜ 收入核算路径判定引擎

- **目标**：合同表单录"核算判定信息"三字段 → 纯函数规则引擎判定 → 快照写合同 + EBS Mock 同步。
- **新表**：无。
- **contracts 加字段**（全 nullable）：`pricing_authority` / `inventory_risk_bearer` / `principal_role` / `revenue_method` / `method_judge_basis`（TEXT，自动生成）/ `method_confirmed_by` / `method_confirmed_at`。
- **新文件**：
  - `backend/app/utils/revenue_rules.py`（**纯函数**，R1/R1b/R2/R3/R4，优先级命中即停）
  - `backend/app/services/revenue_judge_service.py`（判定 + 落合同 + audit_logs + EBS sync `entity_type='contract_revenue_method'`）
  - `backend/app/tests/test_revenue_judge.py`
- **改动文件**：`models/project.py`（Contract 加字段）、`schemas/contract.py`（判定区入参/出参）、`contract_service.py`（保存时触发判定）、合同前端表单组件（"核算判定信息"区 + 实时预览 + 人工覆盖填原因）。
- **算法要点**（**裁定后**，假设 A2/D1）：
  - R1：`business_type=='经营租赁' AND leasing_mode=='自有' AND type==SALES` → 经营租赁
  - R1b：`business_type=='经营租赁' AND leasing_mode IN ('直租','售后回租')` → 服务费（按月确认）
  - R2：`pricing_authority=='上游定价' AND inventory_risk_bearer=='上游' AND principal_role=='代理人'` → 净额法
  - R3：`pricing_authority=='自主定价' AND inventory_risk_bearer=='我方' AND principal_role=='主要责任人' AND 未命中 R1` → 总额法
  - R4：兜底 → 待判定（推送财务总监）
- **测试**：`test_revenue_judge.py`（≥8 条）—— 每条规则命中各 1 + R1/R1b 互斥 + 兜底 + 人工覆盖记 audit + 判定结果 EBS Mock 同步。**关键**：用真实枚举值（`经营租赁`/`自有`/`直租`/`售后回租`）造数据，断言 R1 命中（锁死 D1）。
- **验收门**：5 种判定结果全覆盖；判定依据文本自动生成；只判定不驱动确认（D5）。
- **依赖**：`projects.business_type/leasing_mode`（一期已加 ✓）；D1 裁定。
- **风险**：D1 未裁定则 R1 失效（HIGH，动工前必须裁定）。

### W5-6 ｜ 币种与汇率管理

- **目标**：多币种主数据 + 汇率表 + 现有金额表加币种字段 + 汇兑损益自动计算（service 层）。
- **新表**：`currencies`（code UNIQUE / name / symbol / is_base / active）、`exchange_rates`（from/to/rate_type/rate DECIMAL(18,8)/effective_date/source）、`exchange_gain_loss_rules`（scenario/gl_account_code/description）。
- **现有表加字段**（全 nullable，向后兼容）：`contracts` +`currency_code`+`booked_rate`；`invoices` +`currency_code`+`invoice_rate`；`billings` +`currency_code`+`booked_rate`；`capital_transactions` +`currency_code`+`settlement_rate`+`base_amount`。
- **新文件**：`models/currency.py`、`schemas/currency.py`、`services/exchange_service.py`、`api/v1/endpoints/currencies.py`、`frontend/src/views/ExchangeRateView.vue`。
- **算法要点**：付款/收款核销时 `diff = amount × (invoice_rate − settlement_rate)` → `capital_transactions.category="汇兑损益"`；按 V3.0 3.3.3 经 `payment_settlements.device_id` **按成本占比分摊至设备**（W11-12 表就绪后联动；W5-6 先实现计算 + 落 capital_transactions，分摊在 W11-12 接通）。外币重估留接口不实现。
- **测试**：`test_exchange.py`（≥8 条）—— 汇率 CRUD + 按日/月生效取值 + 汇兑损益正/负/零 golden 算例（真值追值）+ base_amount 换算。**全链路对照表**（D6）：rate 存 DECIMAL(18,8)，amount 乘除后 q2 两位，记每跳。
- **验收门**：**动工前**单位量纲全链路对照表（D6）已出且 review 过（前置检查，防承诺落空）；汇兑损益 golden 3 例（正/负/零）对齐手算；币种字段 nullable 不破坏现有金额。
- **依赖**：无（为 W11-12 分摊提供输入）。
- **风险**：汇率精度/舍入（D6，靠对照表 + golden 防范）。

### W7-8 ｜ 保险管理（设备粒度）

- **目标**：保单 CRUD + 自动投保触发（在途运输险 / 点亮财产险）+ 保费按设备价值占比分摊 + 进资产原值/长期待摊 + 摊销 + 续保/理赔。
- **新表**：`insurance_policies`（project_id/batch_id/policy_type/policy_no/insurer_id→suppliers/insured_amount/premium_rate/premium_amount/start_date/end_date/status/trigger_event/**cost_allocation 资产原值/长期待摊**/amortization_months/claims JSONB/file_path）、`insurance_policy_devices`（policy_id/device_id/allocated_amount）、`insurance_configs`（policy_type/default_rate/insured_ratio/insurer_id/cost_allocation/active）。
- **新文件**：`models/insurance.py`、`schemas/insurance.py`、`services/insurance_service.py`、`api/v1/endpoints/insurance.py`、`frontend/src/views/InsuranceView.vue`。
- **算法要点**：
  - 在途触发：批次设备进"在途"→ 批次总价值 × `insured_ratio` 生成运输险（待确认）→ 保费按设备价值占比分摊到 `insurance_policy_devices`。
  - **保费进原值的折旧交互（硬约束）**：仅设备**点亮前**（转固后到点亮前窗口）归集进原值；点亮后保费一律走长期待摊（不触动折旧算法）。此约束写进 `insurance_service` 校验。
  - 摊销：长期待摊按 `amortization_months` 逐月摊销（复用折旧月度引擎模式），摊销计划接 §4.6 资金预测管线（W13 联调或三期，本阶段先产出计划项）。
  - 续保：`alert_service` 加"保单到期前 30 天"规则；理赔登记更新 `claims` JSONB + status。
- **改动文件**：`device_service`（推进到"在途"/"点亮验收"时触发投保 hook，advisory 不阻塞推进）、`alert_service`（续保规则）、`workflow_service.after_action`（触发）。
- **测试**：`test_insurance.py`（≥8 条）—— 运输险自动生成 + 价值占比分摊 golden + **点亮前/后保费归集约束**（点亮后进原值被拒）+ 摊销计划生成 + 续保 alert。e2e 1 条（UI 录保单 → 设备分摊可见 → 点亮前可归集原值）。
- **验收门**：分摊 golden 对齐；点亮后进原值被拦（防折旧污染）；零回归（推进 hook advisory）。
- **依赖**：`devices` + `device_stages`（一期 ✓）；折旧引擎（只读复用模式）。
- **风险**：保费归集窗口判断时序（设备状态机）；摊销接预测管线的边界。

### W9-10 ｜ 合同深化 + 预付款 + 基础规则（重排：吸收 doc_number/leasing_rule）

- **目标**：合同变更/终止 + 预付款结转（复用 devices 字段，直租退回/回租按月结转）+ 单据编号规则表（回迁一期硬编码 SN）+ 金租规则参数表。
- **新表（4 张）**：`contract_amendments`、`contract_terminations`、`doc_number_rules`（前移自 W11-12）、`leasing_rule_configs`（前移）。〔D2 裁定：预付款复用 devices 字段，不建 prepayments 表〕
- **预付款结转设计（D2 裁定：复用 devices 字段）**：devices 加 `prepayment_settled_amount` 列（累计已结转）；`prepayment_service.py` 每月计费时按规则算结转额累加，全额结转置 `prepayment_settled=True`；一期 `prepayment_settled` 语义不变（零回归）。**不建 prepayments 表**。
- **contracts 加字段**：`purchase_type`、`delivery_terms`/`warranty_terms`/`penalty_terms`、`prepayment_ratio`、销售 `collection_account_type`。
- **新文件**：`models/contract_ext.py`（amendments/terminations）、`services/prepayment_service.py`（结转抵扣逻辑，复用 devices 字段）、`services/contract_amendment_service.py`、`services/doc_number_service.py`（回迁 SN 规则，审计 A8）、`api/...`、前端合同详情页聚合（批次/设备进度/预付款/发票/付款/变更终止时间线/EBS 状态）+ `PrepaymentView.vue`（聚合 devices 行）。
- **doc_number_rules 算法**：前缀+日期+流水，应用于批次号/合同号/付款单号；**回迁一期硬编码 `GPU-{yyyymm}-{seq}` SN 规则**（A8），保持生成结果与一期一致（向后兼容，存量 SN 不变）。
- **测试**：`test_prepayment.py`（≥8 条：申请/审批/支付/直租退回/回租结转/核销回写 settled/余额扣减）+ `test_contract_amendment.py`（变更联动 billings 计划调整 + EBS Mock）+ `test_doc_number.py`（SN 回迁结果一致 + 新规则生成）。
- **验收门**：预付款余额口径单一（D2：devices 字段单源，不双源）；SN 回迁零变化（一期 e2e 全绿）；售后回租 e2e 零回归。
- **依赖**：W5-6 币种（结转列可加 currency）；一期 leaseback 字段（D2 复用）。
- **风险**：D2 已裁定（单源，无双源冲突）；SN 回迁若改了生成结果会破一期设备 e2e（必须结果一致）。

### W11-12 ｜ 付款三重管控 + 通用审批 + 进项侧（重排：减负）

- **目标**：付款申请→审批→登记→核销（多对多，含设备维度 + 汇兑损益分摊）+ 通用审批 + 采购进项税认证/抵扣。
- **新表**（重排后 3 张，原 5 张中的 2 张已前移）：`approvals`、`payment_requests`、`payment_settlements`。
- **payment_settlements**（多对多核心）：`capital_transaction_id` / `invoice_id`（**可空**：待认领/预付款冲抵）/ `batch_id`（可空）/ `prepayment_id`（可空）/ `device_id`（可空，按金额占比逐台多行）/ `amount`。支撑"一笔付款核销多合同/多批次/多台；多笔核销同一批次/单台"；收款核销复用同表。
- **invoices 加字段**（进项侧，审计 A10）：`certification_status`（未认证/已认证/已抵扣）+ `certification_date`。
- **新文件**：`models/payment.py`（approvals/payment_requests/payment_settlements）、`services/approval_service.py`（单级，多级留扩展字段）、`services/payment_service.py`（申请扣减预付款余额 → 审批 → 登记 capital_transactions 多币种+回单 → 核销 payment_settlements + invoice 回填 + 汇兑损益分摊至 device）、`api/...`、进项税台账查询、前端 `PaymentView.vue` + 审批中心。
- **通用审批**：`approvals.biz_type` 含项目立项/付款/预付款/预算调整/监管划转/合同变更/收入确认…；**立项审批双轨**（D4，旧项目/无审批记录走原直接路径）；**提交级校验**：所有业务单据 `project_id` 非空（schemas 层统一）。
- **测试**：`test_payment.py`（≥10 条：申请扣预付款余额 + 审批通过/驳回 + 一笔付多合同多台分摊 golden + 多笔核销同批次 + 待认领收款 invoice_id 空 + 预付款冲抵 + 汇兑损益分摊至设备）+ `test_approval.py`（立项双轨 + 驳回原因必填 + project_id 非空校验）+ `test_input_tax.py`（进项认证/抵扣 + audit + 台账汇总）。
- **验收门**：核销多对多 golden 算例（追值法）对齐；汇兑损益分摊至设备与 W5-6 计算一致；立项审批零回归（wizard-workspace e2e 绿）。
- **依赖**：W5-6 汇兑（计算）+ W9-10 预付款结转（devices 字段扣减/冲抵）+ 一期 invoices（加字段）。
- **风险**：payment_settlements 是二期最复杂表（多对多 + 设备分摊 + 汇兑），是滑期最高风险点——重排后 W11-12 专注它，降低风险。

### W13-14 ｜ 全链联调 + golden 算例 + 端到端

- **目标**：父计划 §3.6 联调链全程跑通：立项（审批）→ 主数据 → 合同（判定+币种）→ 采购 → 预付款 → 设备 7 节点 → 保险触发分摊 → 点亮按台计费 → 开票（含进项认证）→ 付款核销 → 三流对账；EBS Mock 日志完整；汇兑损益 golden。
- **新增 e2e**：`phase2-chain.spec.ts`（一条 journey 串全链，复用 `revenue-chain.spec.ts` 的追值法 + RUN 派生 + E2E- 前缀），断言跨模块数据流（判定结果 → 合同快照 → EBS 日志；保费分摊 → 设备；付款核销 → 发票回填 + 汇兑至设备；进项认证 → 台账）。
- **golden 算例集**：收入判定 5 路径 / 汇兑正负零 / 保费分摊 / 付款多对多核销 / 预付款余额——每例手算真值，代码追值断言。
- **验收门**：phase2-chain e2e 绿；全套 e2e 50+6+1=57 绿（0 flake，债④已治）；pytest 249+35+=284+ 绿；所有迁移可 downgrade。
- **依赖**：W1-12 全部。

---

## 6. 数据迁移与向后兼容（双写铁律）

- **编号**：二期迁移从 `0010_` 起，每张新表一个迁移（或按周聚合），命名 `0010_ebs_mock.py` / `0011_revenue_judge_fields.py` / …。
- **双写**：alembic 迁移 + `db/schema.sql` 同步 + `test_migration_parity.py` 加 case（一期范式）。
- **可逆**：每个迁移实现 `downgrade()`（drop table / drop column），CI 验证 up→down→up。
- **加字段全 nullable**：contracts/invoices/billings/capital_transactions 的所有新字段 nullable + 有默认，存量行不破。
- **不删字段·升为单源**：`devices.prepayment_amount/settled`（D2 裁定）升为预付款单一真源（非冗余），并加 `prepayment_settled_amount` 列；既有字段 nullable 不变。

---

## 7. 测试策略

| 层 | 策略 | 目标数 |
|---|---|---|
| pytest（算法/规则/服务） | 每个新 service 一个 test 文件；金额/汇率/分摊用 golden 真值追值；判定/汇兑/分摊算法覆盖率 100% | +35（249→284+） |
| parity | 每张新表/每个加字段一个 case（迁移 ↔ schema.sql） | +15 表 + ~10 字段 |
| e2e | 每阶段主干 UI 流 1 条 + W13-14 全链串烧 1 条 | +6（50→57） |
| 并发 | 新 e2e 用 RUN 唯一锚点（SN/合同号/RUN），禁 `.first()` 首行假设；全套跑 ≥2 轮确认 0 flake | 债③/债④教训 |

**单位量纲全链路对照表（D6，动工前出）**：对 `invoice_rate`/`settlement_rate`/`booked_rate`/`insured_ratio`/`premium_rate`/payment_settlements 分摊比，各建一行（输入单位/存储/计算/输出/转换点），作为审计与测试依据。

---

## 8. 风险登记册

| ID | 风险 | 级别 | 缓解 |
|---|---|---|---|
| R1 | D1 business_type 枚举未裁定 → R1 失效 | HIGH | W3-4 动工前财务裁定（A2） |
| R2 | payment_settlements 多对多 + 设备分摊复杂 → W11-12 滑期 | HIGH | 重排减负（A4）+ golden 算例 + 全链对照表 |
| R3 | 预付款结转新逻辑与回租既有 `prepayment_settled` 语义冲突 → 回租回归 | MEDIUM | D2 已裁定复用 devices 字段、新列纯加法、`prepayment_settled` 语义不变；售后回租 e2e 守零回归 |
| R4 | EBS 字段映射按假设建 → 真规范来返工 | MEDIUM | 泛化 transform_config（D3），已接受折中 |
| R5 | 汇兑/分摊单位量纲 bug | MEDIUM | 全链对照表 + golden（D6） |
| R6 | 立项审批改流程 → wizard e2e 回归 | MEDIUM | 双轨（D4，与一期 workflow_service advisory 模式一致），cfo 直通 |
| R7 | SN 回迁改生成结果 → 一期设备 e2e 回归 | LOW | 回迁结果必须与硬编码一致（A8） |
| R8 | 一期功能回归面广（33 表 / 24 spec，contracts/invoices/billings/capital_transactions 加字段触碰 pure-reconcile / devices / ownership 链） | MEDIUM | 每周验收门含"一期全套 e2e + pytest 全绿"；加字段全 nullable；改前 grep 引用点 |
| R9 | 二期新 e2e + 共享慢库并发 → 全套 exit 1（债③/债④同类） | MEDIUM | 造数用 RUN 唯一锚点 + E2E-/GPU- 前缀；定位"我的数据"禁 `.first()` 首行假设；全套跑 ≥2 轮确认 0 flake（§4 铁律） |

---

## 9. 裁定结果（2026-08-10 用户拍板，5 项全部定稿）

| 事项 | 裁定 |
|---|---|
| A1 启动时机 | ✅ 授权立即开工，从 W1-2（EBS Mock 骨架）起 |
| A2/D1 business_type | ✅ 规则 R1 改用 `'经营租赁'`（schema CHECK 不动，零迁移） |
| A3 债④ | ✅ 现在就修（同债③ waitForResponse 锚点手法） |
| A4 W11-12 重排 | ✅ 采纳（doc_number_rules / leasing_rule_configs 前移 W9-10；内部排期低风险） |
| D2 预付款 | ✅ 复用 devices 字段，不建 prepayments 表，二期只补按月结转抵扣 service+规则（二期 16→15 表） |

> 5 项全部裁定，计划定稿 v1.2。下一动作：修债④ → 开 W1-2 EBS Mock 骨架。

---

> **文档版本**：v1.2（裁定定稿） | **编写日期**：2026-08-10
> **v1.1→v1.2 变更**：用户裁定 §9 全部 5 项（A1 立即开工 / D1 规则改 `'经营租赁'` / A3 修债④ / A4 采纳重排 / D2 复用 devices 字段、不建 prepayments 表）。D2 致二期新表 16→**15**，§0/§2/§3 D2/§5 W9-10/§6/§8 R3 同步改写。
> **v1.0→v1.1 变更**：经 code-reviewer 审计（PASS-WITH-WARNINGS，无 CRITICAL/HIGH），校正 §1 基线计数（数据表 32→**33**、spec 23→**24**；e2e **50 用例**为 Playwright 运行时枚举真值——静态源码 `test(`=46 含 `all-login.spec.ts` 循环展开 1→5，故 46+4=50，运行时为准）；统一 D4/R6 严重度为 MEDIUM；§8 补 R8（一期回归面）/R9（共享库并发）；W5-6 验收门加"对照表动工前出"前置检查。审计确认 D1/D2/16 表计数/重排无丢 等核心结论证据准确。
> **依据**：父计划 V2.2（2026-08-04）+ 现状实测（33 表 / 249 pytest / 50 e2e / 9 迁移）+ 代码核对（project.py / schema.sql / invoice_service.py / report_service.py / devices.spec.ts / CustomerStatementView.vue）
> **下一状态**：✅ 已授权开工 → 修债④ → 执行 W1-2 EBS Mock 骨架
