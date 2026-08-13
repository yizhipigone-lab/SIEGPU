# SIEGPU ERP 开发接力（Handoff）

> **最后更新**：2026-08-13
> **最近里程碑**：二期全部收官（W13-14 全链联调）+ **三期启动：收入确认管理（§4.2）完成**——pytest 359 绿 / e2e 58 绿 / 浏览器真点 :8088；二期改动已分类提交（4 笔 commit）
> **当前分支**：`main`　**工作区状态**：收入确认阶段改动未提交（等验收后提交），其余已全部入库
> **给接手者**：先读「§3 当前进度」和「§4 铁律」。二期 7 阶段全部完成、15 张新表落地；三期 §4.2 收入确认已完成（见 §3.9）。

---

## 1. 这是什么项目

SIEGPU —— **算力租赁 ERP**（GPU 服务器租给客户、走金租融资、按台计费折旧）。
技术栈：FastAPI + Vue3/naive-ui + PostgreSQL 16 + Docker Compose。

两条主线：

- **一期（已完成）**：管理粒度从「批次」升级到「单台设备」（W1-2 → W9-10 全程）+ 角色化菜单/首页。一期终审已收口（4 条技术债 ①②③④ 全修，pytest 249 / e2e 50 判定「可收」）。
- **二期（进行中）**：业财一体化核心，14 周 / 7 阶段 / 15 张新表。权威计划：[`docs/superpowers/specs/2026-08-10-siegpu-phase2-execution-plan.md`](./superpowers/specs/2026-08-10-siegpu-phase2-execution-plan.md)（v1.2 裁定定稿）。现已完成第 1 阶段 W1-2。

## 2. 怎么跑起来 / 怎么验证

```bash
# 起全栈（db / backend :8000 / frontend :8088）
docker compose up -d

# 后端测试（当前 359 条）
docker compose exec backend pytest app/tests/ -q

# 前端类型检查 + 构建（host 上有 node_modules，可直接跑）
cd frontend && npm run build          # = vue-tsc + vite build
# 注意：vue-tsc 查不出 Vue 模板标签错误，靠 vite build 才抓得到（已踩过）

# e2e（Playwright，当前 58 条；baseURL 走 :8088）
cd e2e && npx playwright test
# 单跑某条：cd e2e && npx playwright test tests/ebs.spec.ts
```

> ⚠️ **端口铁律**：前端 nginx 在 **:8088**（`docker-compose.yml` `8088:80`）。宿主 `localhost:8080` 上有一个**野的本地 python/uvicorn 进程**（非本部署），curl 它会看到 `/login`、`/api/*` 全 404 的假象。**凡是验证前端，一律走 :8088**，不要碰 8080。判别：`curl -D - -o /dev/null http://localhost:PORT/ | grep -i server`——`nginx` 才是前端，`uvicorn` 就是野 8080。改前端代码后必须 `docker compose up -d --build frontend`（restart / 不带 --build 的 up 不生效，nginx 烤的是旧 dist）。

**账号**（密码统一 `sie123`，见 `backend/app/seed.py`）：

| 登录名 | 角色 | 职责 |
| --- | --- | --- |
| admin | ADMIN | 全局 |
| cfo | FINANCE_DIRECTOR | 财务总监，看全部（**e2e 全程用 cfo 登录，菜单勿收紧**） |
| buyer | PROCUREMENT | 采购（第 1-4 步） |
| delivery | DELIVERY | 交付（第 5-8 步） |
| finance | FINANCE_STAFF | 财务专员（第 9-11 步） |

## 3. 当前进度

### 3.1 一期（全部完成并端到端验证）

设备层单台粒度升级 W1-2 → W9-10、角色化菜单、角色化首页 + 职责引导。终审 4 条技术债全修：

- 债①（reconcile 不写 paid_date → autoflush 根因：生产 `SessionLocal autoflush=False` 下设 `invoice_id` 后未 flush 致 matched 恒 0）已修，补显式 flush + paid_date 守卫。
- 债②③④（并发 flake / waitForResponse 锚点）已修。

**一期铁律备忘**：`pytest 绿 ≠ 生产对`——autoflush=False 下 ORM 关系字段设值后必须显式 flush 才能被同事务查询命中。

### 3.2 二期 W1-2（刚完成，✅ 已端到端验证）

**EBS 业财一体化接口 Mock 骨架（仅出站 SIEGPU→EBS）**。Mock 返回 `{status:MOCK_SUCCESS, ebs_reference:MOCK-EBS-{uuid}}`，由 `EBS_MOCK_MODE` 环境变量切换；EBS→SIEGPU 入站属期外里程碑。

| 层 | 内容 | 关键文件 |
| --- | --- | --- |
| 新表（2） | `ebs_field_mappings`（字段映射 transform_rule DIRECT/constant + JSONB config）、`ebs_sync_logs`（含 `entity_version` hash 幂等） | `backend/app/models/ebs.py`、`db/schema.sql`、`alembic/versions/0010_ebs_mock.py` |
| 服务 | Mock HTTP client + 10 个 sync 方法（customer/supplier/contract/invoice/asset/payment/prepayment/lease_disbursement/repayment/goods_receipt）+ 同步服务（entity_version 幂等：同实体同内容二次 sync 跳过不新建 log） | `services/ebs_client.py`、`services/ebs_sync_service.py` |
| REST | 映射配置 CRUD + 日志查询 + `POST /api/ebs/sync/{type}/{id}` 手动触发 + 失败重试 | `api/v1/endpoints/ebs.py`、`schemas/ebs.py`（router 注册在 `main.py` prefix `/api/ebs`） |
| 前端 | EbsMonitor.vue：字段映射配置表 + 手动触发同步 + 同步日志（状态筛选/重试）+ 统计卡 + Mock 横幅 | `frontend/src/views/EbsMonitor.vue`、`router/index.ts`（`/ebs`）、`layouts/MainLayout.vue`（菜单）、`utils/roleMenu.ts`（FINANCE_STAFF 白名单加 `/ebs`） |
| 测试 | `test_ebs_sync.py`（13 条：10 sync 方法 Mock 成功 + 幂等 + 重试 + 转换 + 非 Mock 分支）；e2e `tests/ebs.spec.ts`（映射新增 → 手动触发出站 → 日志 MOCK_SUCCESS → 追值法断言映射转换 → 幂等） | — |

**验证证据**：pytest 262 全绿 / e2e 51 全绿（50 基线 + 1 EBS，零 flake）/ 浏览器 :8088 cfo 登录进 /ebs 四区块渲染正常、console 0 报错、截图存档。

**踩坑记录（已治）**：

- e2e 首跑挂 409——dev 库残留 Phase B 直测建的 `customer/name` 映射撞唯一约束。spec 加防御性预清理 + `cleanup_e2e.py` 补 EBS 两表清理（按 `E2E_` 前缀 + e2e 客户集合清，不碰 demo）。
- 调试时 curl :8080 误判「前端坏了」，实为野 8080 进程；真前端在 :8088。

### 3.3 二期 W3-4（刚完成，✅ 已端到端验证）

**收入核算路径判定引擎**（父计划 §3.2 + 5 项裁定）：合同录「核算判定信息」→ 纯函数规则判定 → 快照写合同 + audit + EBS Mock 出站。**只判定不驱动收入确认**（D5：确认属三期）。

| 层 | 内容 | 关键文件 |
| --- | --- | --- |
| 字段（+7，全 nullable） | contracts：`pricing_authority`/`inventory_risk_bearer`/`principal_role`（判定输入）+ `revenue_method`/`method_judge_basis`（判定快照）+ `method_confirmed_by/at`（人工确认留痕）；audit_logs CHECK 扩 `REVENUE_JUDGE`/`REVENUE_OVERRIDE` | `models/project.py`、`db/schema.sql`、`alembic/versions/0011_revenue_judge_fields.py` |
| 规则 | 纯函数 R1/R1b/R2/R3/R4 优先级命中即停；R1 用真实枚举 `'经营租赁'`（D1 裁定）；PURCHASE 合同不判定（method=None） | `utils/revenue_rules.py` |
| 服务 | 判定+落合同+audit+EBS 出站（`entity_type='contract_revenue_method'`，幂等复用 W1-2）；自动判定门槛=SALES 且（项目有 business_type 或合同有判定输入），无上下文保持 NULL 零回归；人工覆盖原因必填 | `services/revenue_judge_service.py`、`contract_service.py`（create/update 触发） |
| REST | `PATCH /contracts/{id}`（白名单编辑+重判）、`POST /{id}/judge`（手动重判）、`POST /{id}/confirm-method`（人工覆盖）、`GET /contracts/judge-preview`（纯函数预览，须声明在 `/{cid}` 前） | `api/v1/endpoints/contracts.py`、`schemas/contract.py` |
| 前端 | 合同表单「核算判定信息」区（3 下拉+hint）+ 实时预览（300ms 防抖调 preview）+ 详情抽屉判定区 + 「人工确认核算路径」操作（原因必填）；列表加「核算路径」列 | `config/modules.ts`（section/revenueJudge/DetailAction select 扩展）、`components/GenericCrud.vue` |
| 测试 | `test_revenue_judge.py` 13 条（真实枚举值锁 D1：经营租赁/自有→R1 命中）+ parity 3 条；e2e `tests/revenue-judge.spec.ts`（预览 R1→保存自动判定→覆盖净额法→追值+EBS 日志断言） | — |

**验证证据**：pytest 279 全绿 / e2e 52 全绿（全套第 4 轮 0 flake）/ 迁移 up→down→up 实测 / 浏览器 :8088 真点（表单判定区+预览条渲染，console 0 报错，截图 `e2e/screenshots/w3_4-contract-judge-form.png`）。

**踩坑记录（已治）**：

- `audit_logs.action` 是 `VARCHAR(20)` + CHECK 枚举——新动作名必须 ≤20 字符（`REVENUE_METHOD_OVERRIDE` 22 字符被拒，改 `REVENUE_OVERRIDE`）且同步扩 CHECK（schema.sql + 迁移双写，只扩不收窄含全部旧枚举）。
- 迁移 downgrade 收窄 CHECK 会撞存量行：0011 downgrade 先 `DELETE FROM audit_logs WHERE action IN (...)`（0007 guard 范式）再回旧 CHECK，否则 dev 库存量 REVENUE_* 行让 ADD CONSTRAINT 直接失败。
- 全套并发暴露一期隐患（非本次回归，已修）：`CustomerStatementView` 挂载自动选 summary 第一名 + `loadStatement` 无乱序防护 → revenue-chain 全套下两连挂（waitForResponse 超时 / 慢响应覆盖新选择）。修法：spec waitForResponse 前移 goto 前 + 视图加「响应回来时选择已变则丢弃」守卫。

### 3.4 二期 W5-6（刚完成，✅ 已端到端验证）

**币种与汇率管理 + 汇兑损益**（父计划 §3.3）。量纲铁律见 D6 对照表 [`docs/superpowers/specs/2026-08-12-w5-6-unit-dimension-table.md`](./superpowers/specs/2026-08-12-w5-6-unit-dimension-table.md)（动工前已出）：**率存 DECIMAL(18,8) 全精度永不 round；金额两位；唯一乘除跳「外币×率→人民币」才 q2**。

| 层 | 内容 | 关键文件 |
| --- | --- | --- |
| 新表（3） | `currencies`（本币唯一守卫）/ `exchange_rates`（rate 全精度，取值=最近不未来）/ `exchange_gain_loss_rules`（场景→EBS 科目码） | `models/currency.py`、`db/schema.sql`、`alembic/versions/0012_currency_exchange.py` |
| 加字段（全 nullable，NULL=人民币） | contracts(+currency_code+booked_rate) / invoices(+currency_code+invoice_rate) / billings(+currency_code+booked_rate，计费时继承合同币种+按计费日取率) / capital_transactions(+currency_code+settlement_rate+base_amount)；`source_type` CHECK 扩 `'汇兑损益'` | 同上迁移 |
| 汇兑损益 | 核销钩子（`reconcile_invoice`）：同币种非本币+双率齐全 → `diff=q2(外币额×(invoice_rate−settlement_rate))`，正损 OUT/负益 IN/零不落；**不填 invoice_id**（防 matched_amount 污染）；`fx:{txn.id}` 幂等 | `services/exchange_service.py`（`maybe_book_exchange_diff`）、`invoice_service.py` 钩子 |
| REST | `/api/currencies` CRUD+设本币、`/api/exchange-rates` CRUD+`lookup`（同币恒 1、无记录 404 不静默）、`/api/exchange-gain-loss-rules` | `api/v1/endpoints/currencies.py`、`schemas/currency.py` |
| 前端 | ExchangeRateView：币种 tag 区（点击设本币）+ 汇率表 + 试算取值 + 科目规则 | `views/ExchangeRateView.vue`、`router/index.ts`（`/exchange-rates`）、`MainLayout.vue`、`roleMenu.ts`（FINANCE_STAFF 白名单） |
| 测试 | `test_exchange.py` 14 条（golden G1 收益/G2 损失/G3 零/G4 精度 781.89/G5 base_amount 71234.57 + 采购方向相反 + 幂等 + 本币零回归 + 计费继承币种）；e2e `tests/exchange-rates.spec.ts` | — |

**验证证据**：pytest 297 全绿 / e2e 53 全绿（全套第 3 轮 0 flake）/ 迁移 up→down→up 实测 / 浏览器 :8088 真点（三区块渲染，console 0 报错，截图 `e2e/screenshots/w5_6-exchange-rates.png`）。

**踩坑记录（已治）**：

- e2e 弹窗遮罩未退出会拦截后续点击（保存消息出现 ≠ 弹窗已关）→ spec 保存后 `waitFor({state:'hidden'})`；**n-date-picker 回车即确认，绝不可补 Escape**（会连带关掉整个 NModal）。
- 远程下拉（项目/客户）在并发慢库下干等 option 渲染不可靠 → 键入文本收窄再点（`selectRemoteByText`，revenue-chain 同款）。
- 设备维度汇兑分摊未做（按计划留 W11-12 payment_settlements 接通）；外币重估留接口未实现。

### 3.5 二期 W7-8（刚完成，✅ 已端到端验证）

**保险管理（设备粒度）**（父计划 §3.4）：保单 CRUD + 自动投保触发 + 保费按设备价值占比分摊 + 归集原值/长期待摊 + 摊销计划 + 续保 alert + 理赔登记。

| 层 | 内容 | 关键文件 |
| --- | --- | --- |
| 新表（3） | `insurance_policies`（含 `collected_at` 归集幂等哨兵 + `claims` JSONB）/ `insurance_policy_devices`（分摊行）/ `insurance_configs`（险种默认费率/投保比例，无配置=不自动投保） | `models/insurance.py`、`db/schema.sql`、`alembic/versions/0013_insurance.py` |
| 分摊/摊销算法 | `allocate_by_value`（价值占比逐台 q2，**末台吃尾差** Σ 精确）；`amortization_schedule`（月摊 q2，末月尾差） | `services/insurance_service.py` |
| 自动投保 hook | 设备进「在途」→ 批次运输险（每批次一张幂等）；「点亮验收」完成 → 单台财产险（每台一张）。**advisory**：device_service 内 try/except，无配置/失败不阻塞推进 | `device_service.advance_device_stage` |
| 归集硬约束 | `collect_to_asset`：仅「点亮前窗口」（资产卡存在且已转固未运营）可进原值；点亮后（运营中）整单 409 拒（防折旧污染）；先全量校验再动手（无半归集）；collected_at 幂等 | `insurance_service.collect_to_asset` |
| 其他 | 续保 alert（`POLICY_EXPIRING`，到期前 30 天，已生效/理赔中）；理赔登记（claims JSONB + 状态→理赔中）；摊销预览端点（本阶段只产计划项） | `alert_service.py`、`endpoints/insurance.py` |
| 前端 | InsuranceView：保单列表 + 新增（保额×费率实时保费预览 + 设备多选按 SN）+ 详情抽屉（分摊明细/确认/归集/摊销预览/理赔）+ 投保配置卡 | `views/InsuranceView.vue`、`router`（`/insurance`）、`MainLayout`、`roleMenu` |
| 测试 | `test_insurance.py` 11 条（分摊 golden 600/400 + 尾差 333.33×2+333.34 + 自动投保幂等 + 无配置零回归 + 点亮前归集/点亮后硬拒 + 摊销 golden + 理赔 + alert）；e2e `tests/insurance.spec.ts` | — |

**验证证据**：pytest 310 全绿 / e2e 54 全绿（全套 2 轮 0 flake）/ 迁移 up→down→up 实测 / 浏览器 :8088 真点（console 0 报错，截图 `e2e/screenshots/w7_8-insurance.png`）。

**踩坑记录（已治）**：

- naive-ui NInputNumber 的 v-model **blur 才同步**（fill 后 DOM 值对但 model 未更新）→ e2e 填完点别的输入框触发 blur 再断言。
- naive-ui 多选菜单向下展开会盖住下方输入框，「点别处收菜单」会被菜单 option 拦截 → 焦点在多选 input 内按 Escape 只收菜单（先判菜单开着才按，防误关弹窗）。
- pydantic 出参 schema 漏 `model_config = from_attributes` → 端点 500 但前端 catch 吞错只弹 message（抽屉不开），排查时先查网络响应别看 UI。

### 3.6 二期 W9-10（刚完成，✅ 已端到端验证）

**合同深化 + 预付款结转 + 单据编号/金租规则**（父计划 §3.5+§3.6 末，D2 裁定复用 devices 字段、不建 prepayments 表）。

| 层 | 内容 | 关键文件 |
| --- | --- | --- |
| 新表（4） | `contract_amendments`（before/after 快照+原因必填）/ `contract_terminations` / `doc_number_rules`（前缀+日期段+流水，跨段归零）/ `leasing_rule_configs`（键值 upsert） | `models/contract_ext.py`、`alembic/versions/0014_contract_ext.py` |
| 加列 | devices +`prepayment_settled_amount`（D2 单源，NULL 按 0）；contracts +purchase_type/delivery_terms/warranty_terms/penalty_terms/prepayment_ratio/collection_account_type（全 nullable） | 同上迁移 |
| SN 回迁（A8） | `doc_number_service.generate_device_sn` 接管 `device_service.generate_sn`；规则初始化从存量设备读当月最大 seq 接续——**生成结果与一期硬编码完全一致**（test_doc_number 用独立复算老算法对照锁死） | `services/doc_number_service.py` |
| 预付款结转 | 计费钩子（按台计费生成后）：直线法 `q2(总额/合同月数)`，剩余不足月额（≤0.01 尾差）一次结清置 `prepayment_settled=True`；一期回租置位语义不变（已置位直接跳过）；合同月起止缺失不结转；台账 = 聚合 devices 行 | `services/prepayment_service.py`、`billing_service` 钩子 |
| 变更/终止 | 变更金额/月租/止日（快照+audit+EBS update 出站）；月租变更对未来期计费自动生效（计费按周期现算，测试锁死）；终止置已终止+留痕 | `services/contract_amendment_service.py`、`endpoints/contracts.py` |
| 前端 | 合同详情抽屉聚合 tabs（发票/计费单/变更记录/终止记录）+ 变更/终止业务操作；PrepaymentView 台账页（/prepayments） | `config/modules.ts`、`GenericCrud.vue`、`views/PrepaymentView.vue` |
| 测试 | `test_doc_number.py` 5 条 + `test_prepayment.py` 7 条（尾差 golden 333.33×2+333.34）+ `test_contract_amendment.py` 5 条；e2e `tests/contract-ext.spec.ts` | — |

**验证证据**：pytest 329 全绿 / e2e 55 全绿（含售后回租零回归）/ 迁移 up→down→up 实测 / 浏览器 :8088 真点（console 0 报错，截图 `e2e/screenshots/w9_10-contract-detail.png`）。

**踩坑记录（已治）**：

- 尾差收敛边界：`remaining − monthly == 0.01` 恰是 1000/3 的尾差，阈值必须 `<= 0.01`（`<` 永远结不清）。
- GenericCrud 业务操作成功后原先不重拉 detailTabs → 变更记录 tab 显示操作前旧数据；已在 submitAction 补 `loadTabs`。
- `.n-data-table-tr` 的 first() 是**表头行**（naive-ui 表头也用同 class）→ 数据行用 `.n-data-table-tbody .n-data-table-tr`。
- 快照存 Decimal 的 str：经 DB NUMERIC(18,2) 回读带 `.00`（pytest 内存对象 "1000000" vs e2e "1000000.00"）→ e2e 断言用数值比较。

### 3.7 二期 W11-12（刚完成，✅ 已端到端验证）

**付款三重管控 + 通用审批 + 进项税**（父计划 §3.6，二期最复杂模块）。

| 层 | 内容 | 关键文件 |
| --- | --- | --- |
| 新表（3） | `approvals`（单级落地，level/max_level 留多级扩展）/ `payment_requests`（申请→审批→登记→付款）/ `payment_settlements`（多对多核销核心：一笔流水 ↔ 多发票/多批次/多台设备逐台多行，invoice_id 可空=待认领） | `models/payment.py`、`alembic/versions/0015_payment_approval.py` |
| 进项侧 | invoices +`certification_status`+`certification_date`（未认证/已认证/已抵扣）；认证→抵扣状态机 + 台账聚合 + audit | `invoice_service.py`、`endpoints/invoices.py` |
| 三重管控 | 申请（预付款冲抵 ≤ 项目剩余可冲抵额校验）→ 审批（approvals 级联）→ 登记（现金=申请−冲抵，冲抵 FIFO 抵扣 devices 结转列单源）→ 核销 | `services/payment_service.py`、`approval_service.py` |
| 核销多对多 | `settle`：Σ≤流水额、方向校验（OUT→PAYABLE）、发票核销满→已核销+paid_date 兜底（与旧 1:1 reconcile 同语义）；**matched_amount column_property 已扩为「旧链接+新核销行」两路合计**（互斥不双计） | `payment_service.settle`、`models/billing.py` |
| 汇兑分摊至设备 | 外币核销：按核销额算 diff（复用 W5-6 compute_exchange_diff 同口径）→ 落汇兑损益流水 + 按设备价值占比逐台拆核销行（复用保险 allocate_by_value，末台吃尾差）；幂等 `fx:{txn}:{inv}` | `payment_service._book_fx_for_allocation` |
| 立项双轨（D4） | 项目直接创建主流程不变；审批可选附加（不动项目状态）；wizard-workspace e2e 零回归 | `approval_service` + test_approval |
| 前端 | PaymentView：审批中心（待审批通过/驳回必填原因）+ 付款申请（新增/登记/核销多行编辑器）+ 核销记录 | `views/PaymentView.vue`、`router`（`/payments`）、`MainLayout`、`roleMenu` |
| 测试 | `test_payment.py` 10 条（多对多 golden/多笔核销同票/待认领/冲抵 FIFO/汇兑分摊 600/400）+ `test_approval.py` 5 条 + `test_input_tax.py` 4 条；e2e `tests/payment-control.spec.ts` | — |

**验证证据**：pytest 349 全绿 / e2e 56 全绿（全套 2 轮 0 flake，wizard-workspace/售后回租零回归）/ 迁移 up→down→up 实测 / 浏览器 :8088 真点（console 0 报错，截图 `e2e/screenshots/w11_12-payments.png`）。

**踩坑记录（已治）**：

- 外币分摊的「设备归属」：采购合同无 sales_contract_id 设备 → 回退项目内有 purchase_value 的设备（分摊需要价值权重）。
- `Invoice.matched_amount` 是 column_property 纯 SQL 合计——新核销路径不写 `txn.invoice_id`，必须把 payment_settlements 并进 column_property，否则发票池「已核销金额」新路径恒 0。
- e2e 用 style 属性选择器不可靠（浏览器规范化 style 字符串）→ 加语义 class（`.alloc-row`）。

### 3.8 二期 W13-14 + 全局收官（✅ 二期全部完成）

**W13-14 全链联调**：`e2e/tests/phase2-chain.spec.ts` 一条 journey 串全链并逐跳追值——
立项（经营租赁/自有）→ 销售合同（**R1 自动判定经营租赁** + EBS 判定快照出站）→ 采购 → 批次+2 台设备（60万/40万）
→ 在途**自动运输险**（保额 100 万、保费 1000、分摊 golden 600/400）→ 7 节点点亮（**财产险每台一张** + 资产激活）
→ 按台计费（golden 含税 10 万/不含税 88,495.58）→ **预付款月结转 1000**（12000/12）→ 开票（USD@7.10）
→ **进项认证/抵扣**（台账税额 130）→ 收款核销（USD@7.20）→ **汇兑损益 IN 1000 按设备分摊 600/400**
→ 三流对账（billed=B / invoiced=I / received=I 追值）→ UI 收口（/ebs 日志页判定快照可见）。
cleanup 同步扩展（insurance_configs 全清防自动投保误触发 + 各阶段孤儿行兜底），串烧数据全链路清理实测。

**二期全局（7 阶段全 ✅）**：15 张新表全部落地（迁移 0010..0015 逐阶段 up→down→up 实测可逆）；
pytest 249 → **349**（+100）；e2e 50 → **57**（+7 条二期主干 + 全套连续两轮 0 flake）。

| 阶段 | 主题 | 新表 | 状态 |
| --- | --- | --- | --- |
| W1-2 | EBS Mock 骨架（出站） | 2 | ✅ |
| W3-4 | 收入核算判定引擎 | 0 | ✅ |
| W5-6 | 币种 + 汇率 + 汇兑损益 | 3 | ✅ |
| W7-8 | 保险管理（设备粒度） | 3 | ✅ |
| W9-10 | 合同深化 + 预付款结转 + 单据编号/金租规则 | 4 | ✅ |
| W11-12 | 付款三重管控 + 通用审批 + 进项税 | 3 | ✅ |
| W13-14 | 全链联调 + golden 算例 + 端到端串烧 | 0 | ✅ |

**期外里程碑（未做，父计划 §0.3）**：EBS 真对接（Mock→真规范映射可能返工，已接受折中；「发 EBS 接口规范申请函」外部动作仍挂起）、外币重估、EBS 入站。

### 3.9 三期 §4.2 收入确认管理（刚完成，✅ 已端到端验证）

**收入确认 + 科目映射**：计费自动出确认**草稿**（不含税权责口径，单台粒度，`billing_id` 幂等）→ 通用审批（`收入确认` biz_type，审批中心通过/驳回）→ 通过 → 已确认 + 按 `gl_account_mappings` 生成 Mock 凭证（方法精确映射优先，通用兜底，缺映射标 `mapping_missing` 不静默错账）→ EBS 出站 → 已同步EBS。

| 层 | 内容 | 关键文件 |
| --- | --- | --- |
| 新表（2） | `revenue_recognitions`（uq_revrec_billing 幂等）/ `gl_account_mappings`（event+method 唯一） | `models/revenue.py`、`alembic/versions/0016_revenue_recognition.py` |
| 服务 | 计费钩子（device/order 两维都挂）+ 审批级联（approval_service._cascade 加「收入确认」分支）+ 凭证生成 + EBS `entity_type='revenue_recognition'` | `services/revenue_recognition_service.py`、`billing_service.py` 钩子 |
| 前端 | RevenueRecognitionView：确认单列表 + 凭证弹窗（借贷科目）+ 科目映射卡 + 存量补草稿 | `views/RevenueRecognitionView.vue`、`router`（`/revenue-recognitions`） |
| 测试 | `test_revenue_recognition.py` 8 条（草稿自动生成/方法快照/凭证 golden 1122.01→6001.01/通用兜底/缺映射标记/驳回保草稿/补建幂等/映射防重）；e2e `tests/revenue-recognition.spec.ts` | — |

**验证证据**：pytest 359 全绿 / e2e 58 全绿 / 迁移 up→down→up 实测 / 浏览器真点（截图 `e2e/screenshots/p3-revenue-recognition.png`）。

**踩坑**：`approvals.submitted_by` 是硬 FK——老测试用随机 UUID 作 actor 直接撞外键；submit 改为「用户不存在降级 NULL」（同 audit_service 范式）。

**二期 5 项裁定（v1.2 全定稿，接手勿推翻）**：① 立即开工从 W1-2 起 ② R1 规则用 `'经营租赁'`（schema CHECK 不动，零迁移）③ 债④ 现在就修（已修）④ W11-12 重排（doc_number/leasing_rule 前移 W9-10）⑤ D2 预付款复用 devices 字段、不建 prepayments 表（二期 16→15 表）。

## 4. 铁律（必读，违反会出事）

- **🚫 不 git commit** —— 用户未授权不提交（用户明确点名才提）。
- **端到端验证铁律** —— 实现只在「浏览器真点能验证」时才算完（走 :8088），「后端跑通」不是终点。
- **分析必须验证不猜测** —— 下结论前实测/读代码/拿原始数据；多假设逐一排除，不堆「可能 A/B」。
- **Docker 镜像无 source mount** —— 改代码必须 `docker compose build <svc>` + `up -d <svc>`；前端尤其要 `--build`。
- **service 不 commit** —— service 函数只 `flush`，commit 在 endpoint / scheduler。
- **schema 改动双写 + 可逆** —— alembic 迁移 + `schema.sql` + `test_migration_parity.py`，必须 `downgrade` 可回滚。conftest 从 schema.sql 建测试库（非 alembic）。
- **cfo 菜单别收紧** —— e2e 全程用 cfo，收紧会大面积回归。
- **Dashboard 待办卡 title 必须保「待处理」** —— wizard-workspace e2e 用它定位。
- **F1 消息提醒仅应用内铃铛+红点**（NO email/企微）。安全问题目前全搁置（改密/权限拦截/审计 UI）。
- **e2e 无测试隔离** —— 用 `RUN=Date.now().toString(36)` 派生唯一数据 + `E2E-`/`GPU-` 前缀；`globalTeardown` 跑 `cleanup_e2e.py` 清理（每次 run 后，含单 spec）。定位「我的数据」用唯一锚点，**禁 `.first()` 首行假设**（债③教训）。
- **db 连接池** `pool_size=20 / max_overflow=20`。
- **开发质量三规则**：先问清楚再动手 / 出结果后自检迭代 / 不破坏现有功能（向后兼容）。
- **回答时间戳**：每轮回复开头打印开始时间，末尾附「当前时间 + 本次回答经过」。

## 5. 关键文件地图

**前端**（`frontend/src/`）

- `utils/roleMenu.ts` —— 菜单过滤单一事实源（改菜单只动这里；`/ebs` 已加 FINANCE_STAFF）
- `utils/roleGuide.ts` —— 角色引导单一事实源（改职责文案只动这里）
- `views/EbsMonitor.vue` —— 二期 W1-2 EBS 监控页（映射/触发/日志/统计）
- `layouts/MainLayout.vue` —— 侧栏 + 顶栏逃生口（菜单项含 EBS 监控）
- `router/index.ts` —— 路由 + 守卫（`/ebs` 已注册）
- `views/Dashboard.vue` —— 首页（角色化）
- `stores/auth.ts` —— `auth.role`（pinia）+ localStorage

**后端**（`backend/app/`）

- `services/payment_service.py` + `approval_service.py` —— 二期 W11-12 付款三重管控/多对多核销/汇兑分摊至设备 + 通用审批
- `services/doc_number_service.py` —— 二期 W9-10 单据编号（SN 规则回迁，A8 零变化锁死）
- `services/prepayment_service.py` —— 二期 W9-10 预付款按月结转（D2：devices 字段单源）
- `services/contract_amendment_service.py` —— 二期 W9-10 合同变更/终止 + 金租规则键值
- `services/insurance_service.py` + `models/insurance.py` —— 二期 W7-8 保单/分摊/归集硬约束/自动投保 hook/摊销
- `services/exchange_service.py` —— 二期 W5-6 汇率取值（最近不未来）+ 汇兑损益核销钩子（量纲见 D6 对照表）
- `models/currency.py` + `api/v1/endpoints/currencies.py` + `schemas/currency.py` —— 币种/汇率/科目规则
- `utils/revenue_rules.py` + `services/revenue_judge_service.py` —— 二期 W3-4 收入判定纯函数规则（R1-R4）+ 判定/覆盖/EBS 出站
- `services/ebs_client.py` + `ebs_sync_service.py` —— 二期 EBS Mock client + 10 sync + 幂等
- `api/v1/endpoints/ebs.py` + `schemas/ebs.py` + `models/ebs.py` —— EBS REST/ORM
- `services/workflow_service.py` —— 11 步权威流程 + `get_my_tasks`（按 doer_role 派活）
- `services/device_service.py` —— 设备状态机 + 资产/off_balance 同步
- `services/report_service.py` —— 对账单（`received` 读 `paid_date IS NOT NULL`）
- `scripts/cleanup_e2e.py` —— dev-DB e2e 数据清理（globalTeardown 调）
- `db/schema.sql` + `alembic/versions/0001..0015` —— schema 双写（0010=ebs_mock，0011=revenue_judge_fields，0012=currency_exchange，0013=insurance，0014=contract_ext，0015=payment_approval）

**规格 / 计划**

- `docs/superpowers/specs/2026-08-10-siegpu-phase2-execution-plan.md` —— **二期权威执行计划**（逐周/逐表/逐测试，含 W3-14 详细设计）
- `docs/superpowers/specs/2026-08-04-siegpu-upgrade-plan.md` —— 父计划（一期+二期总规划）

## 6. 已知坑（踩过，别再踩）

| 坑 | 说明 / 规避 |
| --- | --- |
| **audit_logs.action 是 VARCHAR(20)+CHECK 枚举** | 新 audit 动作名 ≤20 字符，且必须同步扩 CHECK（schema.sql + alembic 双写，含全部旧枚举只扩不收窄）；downgrade 收窄前先 DELETE 新动作行（0007 guard 范式），否则存量行让 ADD CONSTRAINT 失败 |
| **宿主 :8080 是野 uvicorn，前端在 :8088** | curl/MCP 验证前端一律 :8088；判别看 `server:` header（nginx vs uvicorn）。详见 §2 |
| **改前端 restart/up 不带 --build 不生效** | nginx 构建时烤 dist，无 source mount；必须 `up -d --build frontend` |
| **pytest 绿 ≠ 生产对（autoflush 铁律）** | 生产 `SessionLocal autoflush=False`；ORM 关系字段设值后须显式 flush 才被同事务查询命中（债①根因） |
| **reconcile 与对账单不对称** | 完整核销只写 matched_amount 不写 paid_date → 不动对账单 `received`；驱动 received 用 `POST /invoices/{id}/pay`。潜在隐性 bug，二期未修，仅记 |
| **Dashboard 待办卡 title 保「待处理」** | e2e `.n-card hasText:'待处理'` 定位；横幅文本避开此三字 |
| **vue-tsc 查不出模板标签错误** | 自闭合标签多余闭合 vue-tsc 绿但 vite build 报错；改完前端跑 `npm run build` |
| **naive-ui NSelect Playwright 三坑** | placeholder 不在 input / 残留隐藏 option / 过渡动画时序；封装见 memory `naive-ui-select-playwright` |
| **e2e 写共享 dev DB 无隔离** | 历史 99 条采购待办曾压垮 `get_my_tasks`（无 LIMIT）致 wizard flake；已加 `cleanup_e2e.py` + globalTeardown 治理 |

## 7. 给下一步的建议

**下一棒建议（二期已收官，三期 §4.2 已完成）**：

1. **三期 §4.3 对账中心完善（1 维 → 7 维）**：销售全链路穿透（合同→计费→开票→收款→**已确认收入**）、采购四单、资产交付、监管账户、汇兑损益、业财一致性（Mock 下手动注入 3 条模拟差异验证展示管道）、三流差异明细。
2. **三期 §4.4 采购退货 + 合同终止（设备粒度）**：`return_orders` / `return_order_devices`。
3. **顺手待办**：「发 EBS 接口规范申请函」（外部流程，W1 起挂着）；`e2e/fetch-doubao.js` 来源待确认，勿盲目提交。

**接手者第一件事**：跟用户确认走哪条。**不要未经确认就开新实现**（规则1：先问清楚）。

> 工作区现状提示：二期已全部入库（4 笔 commit）；三期 §4.2 收入确认改动待验收后提交。

## 8. 跨会话 memory（`~/.claude/projects/e--1target-SIEGPU/memory/`）

- `project-siegpu-erp.md` —— 项目设计 v2.0 + 代码骨架 + 运行方式
- `siegpu-upgrade-device-layer.md` —— 一期设备层升级全程（W1-2→W9-10 终审 + 债① autoflush 根因）
- `end-to-end-verification-iron-law.md` —— 端到端验证铁律（2026-08-01 向导工作台事故）
- `docker-frontend-rebuild-not-restart.md` —— 前端 rebuild 必须 --build + **:8080 野进程 / 真前端 :8088**
- `e2e-devdb-pollution-teardown.md` —— e2e 共享库污染 + cleanup_e2e/globalTeardown 治理
- `naive-ui-select-playwright.md` —— naive-ui 下拉 e2e 三坑封装
- `role-based-menu.md` —— 角色化菜单 + 逃生口 + 路由守卫
- `role-dashboard-guide.md` —— 角色化首页 + 职责引导
- `docs-md-convention.md` —— 项目自建 .md 放 docs/ 下

---

> **文档版本**：2026-08-13（二期收官 + 三期 §4.2 收入确认版）｜**下一状态**：三期 §4.3 对账中心 / §4.4 退货链路（等用户拍板）
