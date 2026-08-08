# SIEGPU 算力租赁 ERP — 工作成果汇报

> **生成时间**：2026-08-08
> **汇报范围**：项目启动至今全部已完成工作 + 当前状态 + 待办路线
> **当前分支**：`main`　**工作区**：大量未提交改动（设备层升级 + 角色化 UX + 易用性补强），**未 git commit（用户未授权）**
> **一句话状态**：一期核心 + 设备层升级（W1-2→W7-8）+ 角色化 UX 全部端到端验证通过；pytest **225 绿** / e2e **44 绿**；剩 3 条 UX 补强项（API 权限拦截 / 强制改密 / 审计查看 UI）待做。

---

## 0. 状态快照（先看这张表）

| 模块 | 状态 | 验证 | 关键产出 |
|---|---|---|---|
| 一期三核心（资金池/金租/计费发票） | ✅ 已交付 | pytest | 资金池头寸、9 节点金租流程、三流对账 + 红冲 |
| 主数据/合同/订单交付/资产折旧/报表/利润/Excel | ✅ 已交付 | pytest | 通用 CRUD、6 阶段交付、IRR/NPV 测算、导入导出 |
| 向导式工作台（18 步） | ✅ 已交付（含事故修复） | e2e | 项目工作台 + 待办派活；催生"端到端验证铁律" |
| 设备层 W1-2（设备地基） | ✅ 已交付 | pytest+e2e | devices/batch_devices/off_balance 三表 + 7 节点状态机 |
| 设备层 W3-4（交付节点设备化） | ✅ 已交付 | 150+37 | device_stages 7 节点 + 双轨防双计三纪律 |
| 设备层 W5-6（一机一卡 + 按台计费） | ✅ 已交付 + 审计闭环 | 187+41 | 转固/折旧分离、按台计费、4 项审计已修 |
| 设备层 W7-8（金租双模式 + 售后回租 + 放款联动） | ✅ 已交付 | **225+44** | settle_ownership、回租出售全链路、放款阈值联动 |
| 角色化菜单 | ✅ 已交付 | e2e 44 | 按角色过滤 + 逃生口 + 路由守卫 |
| 角色化首页 + 职责引导 | ✅ 已交付 | e2e 44 | 横幅 + 待办主角 + 11 步流程弹窗 |
| **UX-3 表单单位强提示 + 百分比兜底**（本次会话） | ✅ 已交付 | build+27e2e+浏览器 | 12 文件 label 加单位 + ProfitView 值>1 兜底 |
| UX-1 API 权限拦截 | ⏳ 待做 | — | 只拦高危动作（删除/红冲/放款/审批） |
| UX-2 首次登录强制改密 | ⏳ 待做 | — | must_change_password + 改密端点 + 守卫 |
| UX-4 审计查看 UI | ⏳ 待做 | — | GET /audit-logs + AuditView |
| W9-10 联调回归 + 一期终审 | ⏳ 待做 | — | 一期收尾 |

> ⚠️ **纠正 `docs/HANDOFF.md` §3**：该文件把 W7-8 列为「未完成」、基线写 187，**已过时**。实测 W7-8 全部落地（见 §3.4），pytest **225** collected、e2e **44**。后续应同步更新 HANDOFF。

---

## 1. 项目概况

**SIEGPU** —— 赛意信息（300687）的「算力租赁 ERP」：把 GPU 服务器租给客户、走金融租赁融资、按单台设备计费折旧。

**技术栈**：FastAPI + Vue3/naive-ui + PostgreSQL 16 + Docker Compose。

**三大业务痛点**（系统核心解决）：
1. **资金池头寸** —— 多项目共用资金池，要算清净头寸、防超拨
2. **金租审批流程** —— 9 节点流程 + 放款生成还款计划 + 资金入金
3. **合同发票对账** —— 三流（合同/发票/付款）对账、超开拦截、红冲

**主线工程**：把管理粒度从「批次」升级到「单台设备」的一期改造（V3.0 计划，分 W1-2 → W9-10 推进）。权威计划书：`docs/superpowers/specs/2026-08-04-siegpu-upgrade-plan.md`（V2.2，含 §10 审计记录）。

---

## 2. 已完成工作成果（按里程碑）

### 里程碑 A — 一期核心交付（v2.0 设计落地）

基于 `docs/superpowers/specs/2026-07-30-siegpu-erp-design-v2.md`（19 表 + 状态机 + 幂等事务 + 红冲 + 权限矩阵 + 业务算法 + 测试策略）。

| 成果 | 内容 | 关键文件 |
|---|---|---|
| **① 资金池** | 多项目共用池 + 调配/归还 + 红冲 + 净头寸 | `services/capital_service.py`、`views/CapitalView.vue` |
| **② 金租流程** | 9 节点审批 + 放款→流水 + 还款计划（月/季/半年） | `services/leasing_service.py`、`utils/repayment_plan.py` |
| **③ 计费 + 发票** | billings 计费 + invoices 开票 + 三流对账 + 超开 + 红冲 | `services/billing_service.py`、`services/invoice_service.py` |
| 主数据/合同/订单交付 | 通用 CRUD（8 模块配置驱动）+ 6 阶段交付 + 点亮→资产折旧 | `config/modules.ts`、`services/order_service.py` |
| 报表 + 利润测算 | 资金月报、项目概览、应收账龄；IRR/NPV/回本月度现金流 | `services/report_service.py`、`profit_service.py` |
| Excel 导入导出 | 多实体导出 + suppliers/customers 导入（openpyxl） | `services/*_service.py` |
| 应用内告警 | §5.8 告警引擎 | `services/alert_service.py` |
| 代码骨架审计 + TOP7 修复 | `AUDIT-2026-07-31-siegpu-scaffold.md`（FAIL 0/WARN 12/PASS 8）全部修复 | `core/`、`db.py` |

**关键修复**：软删除默认过滤（`with_loader_criteria`）、部分唯一索引对齐、JWT_SECRET 启动校验、事务范式（service flush / endpoint commit）、IntegrityError handler、bcrypt 5.0×passlib 不兼容（改直用 bcrypt）。

### 里程碑 A+ — 向导式工作台（18 步）+ 事故修复

| 成果 | 内容 |
|---|---|
| 项目工作台 | `/projects/:id/workspace` 18 步向导 + 进度条 + 时间线 + 抽屉办理 |
| 待办派活 | `/workflows/my-tasks` + `get_my_tasks` 按 doer_role 过滤 |

> ⚠️ **事故教训（催生铁律）**：2026-08-01 后端引擎完整、API 正确、72 测试全绿，但前端 8 个抽屉步骤只弹"待实现"、跳转路由写错——**用户实际走不通**。修复后确立「端到端验证铁律」（见 §6）：**"代码写完"≠"任务完成"，完成线是用户在界面端到端走通**。

### 里程碑 B — 设备层升级一期（V3.0：批次 → 单台）

#### B1. W1-2 设备地基 ✅
- 3 张新表：`devices` / `batch_devices` / `off_balance_registers` + 7 表字段扩展
- `device_service` + `/api/devices`；迁移 `0005_device_layer.py`
- 前端 `DevicesView.vue` + 路由 + e2e 4/4

#### B2. W3-4 交付节点设备化 ✅（pytest 150 / e2e 37）
- `device_stages` 表：7 节点（订货/在途/到货/己方压测/上架/客户压测/点亮验收）× 4 状态；`不合格→进行中` 可返工
- 设备状态机：`advance_device_stage` / `advance_batch_stages` / `_derive_device_status` / `resolve_flow_type`（只升不降）
- **双轨三条纪律（防双计）**：三旧入口（advance_stage / light_on / generate_billing）顶部统一过 `assert_legacy_path`，对 device 订单返 409 FLOW_TYPE_DEVICE
- device-flow-7stage 向导模板（10 步）；`seed_templates` 改按 name 幂等（增量自愈）
- **自检修 2 个真 bug**：① OrderDetail 响应漏 is_batch/flow_type（三端点不一致）② billing 防双计闸错位（缺 monthly_rent 先抛 BAD_REQUEST 而非 FLOW_TYPE_DEVICE）

#### B3. W5-6 一机一卡 + 按台计费 + 审计闭环 ✅（pytest 187 / e2e 41）
- 迁移 `0007_asset_per_device.py`：assets `+device_id`（部分唯一）+ `+operation_status` + 6 折旧字段放宽 nullable；billings 唯一索引漂移修复（`(order,period)`→`(device_id,period_index)`）；存量批量卡按 quantity 拆 N 台（Σ 不变量自检）
- **转固/折旧分离（D1）**：上架→建资产卡（已转固未运营，折旧全 NULL）；点亮验收→激活（填折旧+运营中，幂等）
- **按台计费（D2/D3）**：`generate_billing_device`（读 device_stages 点亮验收日期、经 sales_contract 反查订单、金额用 device.monthly_price）+ `POST /billings/device`
- **D5 返工守门**：点亮验收专属 `_assert_light_rework_safe`（已有运营中资产/计费→409「先红冲与处置」）
- **M-1 翻转**：单台订单挂设备→flow_type=device→拦死 bulk 入口
- **审计闭环**（`docs/superpowers/audits/2026-08-07-w5-6-post-audit.md`，PASS 有条件 0C/1H/8M）：HIGH「`advance_batch_stages` 半提交泄漏」改 `with db.begin_nested()` SAVEPOINT 隔离；3 个关键 MEDIUM 全修

#### B4. W7-8 金租双模式权属分叉 + 售后回租 + 放款联动 ✅（pytest 225 / e2e 44）
> 计划：`~/.claude/plans/cheeky-hopping-shore.md`（5 Phase，4 条决策已锁定）

- **迁移 `0008_leaseback_and_disbursement.py`**（schema.sql 双写，真·无损可逆已 throwaway 库往返验证）：新表 `long_term_payables`（per-device 部分唯一）+ orders `+disbursement_threshold_pct`(NUMERIC 5,2 DEFAULT 100) / `+disbursement_todo_process_id`(幂等哨兵) + devices `+prepayment_settled` + audit_logs CHECK 扩至 18 枚举
- **权属派生（D1）**：纯函数 `derive_ownership(leasing_mode)`（`utils/ownership.py:21`，自有→表内 / 直租→金租表外 / 售后回租→表内），落点 `_sync_device_asset` 上架分支（`device_service.py:300`，仅当 `device.ownership` 为 None 时由 leasing_mode 派生）；显式入参永远优先（守旧测试零回归）。注：「settle_ownership」是设计概念名/落点描述，**非函数名**，真实函数是 `derive_ownership`
- **售后回租出售全链路** `services/leaseback_sale_service.py` + `POST /devices/{id}/leaseback-sale`：守门 → `truncated_schedule` 折旧截断（末期吸收尾差）+ 已处置 → off_balance 建档 → LongTermPayable 确认（carrying+sale_gain_loss）→ prepayment_settled → 审计 LEASEBACK_SALE。**不提供 reverse**（折旧截断后已过期间不自动红冲，二期补）
- **放款联动 hook**：点亮验收已完成 + 有 batch_id 时，`_batch_light_completion` 派生计数（不存储，返工自动降 pct）→ 达 `disbursement_threshold_pct` → `_ensure_disbursement_leasing_process` 零改复用 `create_process`；哨兵单点幂等
- **融资分类字段**：LeasingProcess 出参加 materials + leasing_mode/financing_type；向导插 step 9 金租放款（10→11 步）；前端 DevicesView 回租出售按钮、LeasingView 新建表单 3 字段
- **W7-8 三条教训**：① 向导模板也有 folding（DB 冻结快照需 seed 主动同步代码演进，改 seed 为 upsert）② db.py 连接池默认值扛不住全量 e2e 并发（调到 pool_size=20/max_overflow=20）③ e2e 行定位数据必须跨 RUN 唯一（金额也行，不只 SN）

### 里程碑 C — 角色化 UX

#### C1. 角色化菜单 ✅（2026-08-07）
- 单一事实源 `frontend/src/utils/roleMenu.ts`：ADMIN/FINANCE_DIRECTOR 看全部（**cfo 勿收紧，e2e 全程用 cfo**）；FINANCE_STAFF/PROCUREMENT/DELIVERY 按职责过滤；空 role fail-open 看全部
- 顶栏「我的角色/全部菜单」逃生口（localStorage 记忆，一人多角）
- 路由守卫：直接输 URL 访问无权页→回首页；工作台对所有角色放行

#### C2. 角色化首页 + 职责引导 ✅（2026-08-07）
- 单一事实源 `frontend/src/utils/roleGuide.ts`：采购=Step1-4、交付=Step5-8、财务=Step9-11（依据 `_device_flow_steps` 11 步 doer_role）
- `Dashboard.vue` 双分支：执行角色=职责横幅 + 精简 KPI + 待办主角 + 11 步流程弹窗高亮；admin/cfo=原财务首页（不动）
- **e2e 兼容铁律**：待办卡 title 必须保「待处理」（wizard-workspace 用 `.n-card hasText:'待处理'` 定位）；横幅文本绝不能含「待处理」三字

### 里程碑 D — 易用性补强（本次会话）

#### D1. UX-3 表单单位强提示 + 百分比兜底 ✅（2026-08-08）
> 用户决策：「快速层——改 label + 百分比兜底」，不动架构（不加 FieldConfig.suffix / moneyCny 辅助函数）

**改动 12 文件**：
| 类型 | 改动 |
|---|---|
| 百分比兜底（ProfitView） | 年利率/自有比例/残值率 → 标签加「小数,如0.04」+ `:status` 黄框；值 > 1 弹"⚠ 百分比请填小数，请确认未把 4% 填成 4"。**非阻塞**（只提醒不拦提交，极端合法值不受影响） |
| 金额字段 | 采购原值(元) / 月计费额(元/月) / 月租金(含税,元/月) / 出售价(元) / 授信额度(元) / 合同金额(不含税,元) / 含税金额(元) |
| 数量/期数 | 数量→`(台)`、计费期数/期数→`(期)`、合格数/不合格数→`(台)` |
| 金租表单 | 申请金额/实际放款/还本/付息/年利率/期数 全带单位 |
| GenericCrud 配置 | modules.ts 设备参考单价/银行授信/项目总投资/合同金额/月租/订单数量单价 → 表单标签带单位 |

**涉及文件**：`ProfitView.vue`、`LeasingView.vue`、`DevicesView.vue`、`CapitalView.vue`、`InvoicesView.vue`、`AcceptancesView.vue`、`BillingsView.vue`、`SalesOrdersView.vue`、`config/modules.ts`、`step-forms/{Billing,Invoice,Acceptance}Form.vue`

---

## 3. 本次接力会话工作明细（2026-08-08）

| 步骤 | 内容 | 结果 |
|---|---|---|
| 1. 盘点接力状态 | 读 HANDOFF + memory，实测 pytest baseline | 发现 HANDOFF §3 过时：实际 **225**（非 187），W7-8 已落地 |
| 2. 锁定决策（两轮 AskUserQuestion） | 节奏 / 顺序 / 范围 | UX 先于 W7-8；UX-3→UX-2→UX-4→UX-1；UX-1 只拦高危；UX-3 走快速层 |
| 3. UX-3 e2e 安全核查 | grep e2e 定位器 | `hasText:'申请金额'` 子串匹配，改"申请金额(元)"仍命中；无 locator 依赖被改 label |
| 4. UX-3 实现 | 12 文件 label + ProfitView 百分比兜底 | 全部 Edit 完成 |
| 5. UX-3 验证 | build + e2e + 浏览器 | 见下 |
| 6. 本汇报 | 产出本文档 | — |

**UX-3 验证证据**：
- ✅ `vue-tsc + vite build`：28s 绿，0 类型错误
- ✅ e2e 回归（27 核心流程：金租/计费/验收/向导/设备/资金/5 账号登录）：全过（51s）
- ✅ 浏览器实测（真 chromium）：ProfitView 单位标签可见、年利率填 4 触发兜底警告；设备型号新建表单"参考单价(元)"可见
- ⏭ pytest 跳过（纯前端，未动 .py，后端基线 225 不受影响）

---

## 4. 当前验证基线

| 维度 | 数量 | 命令 |
|---|---|---|
| 后端单测 | **225 passed** | `docker compose exec backend pytest app/tests/ -q` |
| E2E | **44 passed** | `cd e2e && npx playwright test` |
| alembic check | ⚠️ **非零（FAILED）** | `docker compose exec backend alembic check` |
| 前端类型 + 构建 | 绿 | `cd frontend && npm run build` |

> 实测时间 2026-08-08。pytest `225 tests collected` 已实跑确认；e2e 44 已 `--list` 确认；`alembic check` 一手复现 **FAILED**（见 §9 已知坑，**非零 diff**）。

---

## 5. 待办与下一步路线

### 5.1 UX 补强（用户已排期，本次会话锁定顺序）

| 项 | 内容 | 风险 | 状态 |
|---|---|---|---|
| **UX-2** 首次登录强制改密 | User 加 `must_change_password` + 迁移 + 改密端点 + 前端 ChangePassword 页 + 路由守卫 + seed 标记 | 中（动后端+DB） | ⏳ 下一条 |
| **UX-4** 审计查看 UI | 后端 `GET /audit-logs`（过滤/分页）+ Pydantic schema + 权限门 ADMIN/FINANCE_DIRECTOR + 前端 AuditView + 路由/菜单 + `idx_audit_at` 索引 | 中（动后端） | ⏳ |
| **UX-1** API 权限拦截 | 只拦高危动作（务实）：删除=ADMIN；红冲/金租放款/验收审批/跳过·强制完成=ADMIN+FD；create/edit 开放；pytest 403 + e2e | 高（碰 e2e，cfo 全程登录） | ⏳ |

> UX-1 已锁定策略：用现成 `require_role(*roles)`（`core/deps.py:28`）只 gate 高危动作，保留 cfo 全量（否则破 e2e）。权限矩阵设计见 `docs/superpowers/specs/2026-08-01-siegpu-p0-security-p1-multiproject-plan.md` §7。

### 5.2 一期收尾

- **W9-10** 联调回归 + 一期终审

### 5.3 设计债 / 可调点（已记录，未排期）

- 利润测算硬编码（60 月/4%/opex，未读 LeasingProcess/Contract.tax_rate；disbursement_date 写死 2026-01-01；错误以 200+{error} 破坏 BusinessError 契约）
- 回租出售无 reverse 端点（折旧截断后已过期间不自动红冲，二期补）
- 邮件/企业微信通知（现为应用内告警）
- e2e 测试数据无隔离（写共享 dev 库，累积污染致设备列表卡顿；根治需 per-run schema 重置）
- 角色化首页 3 可调点：① 待办卡太长可分页/折叠 ② 横幅关闭无召回入口 ③ flowRange 基于 11 步，18 步默认模板项目步号对不上

---

## 6. 铁律（接手必读，违反会出事）

- **🚫 不 git commit** —— 用户未授权。改动留工作区，`git diff --stat` 评估即可。
- **端到端验证铁律** —— 实现只在「浏览器真点能验证」时才算完，「后端跑通」不是终点（2026-08-01 向导事故教训）。
- **分析必须验证不猜测** —— 下结论前实测/读代码/拿原始数据；多假设逐一排除，不堆「可能 A/B」。
- **Docker 镜像无 source mount** —— 每次改代码必须 `docker compose build <svc>` + `up -d <svc>`。
- **每期结束 pytest + e2e 必须全绿**；新增测试 ≥25 条/期；纯函数 100% 覆盖。
- **schema 改动**：alembic 迁移 + `schema.sql` 双写 + parity 测试，**必须可逆**。
- **开发质量三规则**：先问清楚再动手 / 出结果后自检迭代 / 不破坏现有功能（向后兼容）。

---

## 7. 运行 / 验证 / 账号速查

```bash
# 起全栈（db / backend :8000 / frontend :8080）
docker compose up -d

# 后端测试
docker compose exec backend pytest app/tests/ -q

# 前端类型 + 构建（host 上有 node_modules）
cd frontend && npm run build          # vue-tsc + vite build

# e2e
cd e2e && npx playwright test
```

**账号**（密码统一 `sie123`，见 `backend/app/seed.py`）：
| 登录名 | 角色 | 职责 |
|---|---|---|
| admin | ADMIN | 全局 |
| cfo | FINANCE_DIRECTOR | 财务总监，看全部 |
| buyer | PROCUREMENT | 采购（第 1-4 步） |
| delivery | DELIVERY | 交付（第 5-8 步） |
| finance | FINANCE_STAFF | 财务专员（第 9-11 步） |

---

## 8. 关键文件地图

**前端**（`frontend/src/`）
- `utils/roleMenu.ts` / `roleGuide.ts` / `role.ts` —— 角色化三大单一事实源
- `views/Dashboard.vue` —— 首页双分支｜`layouts/MainLayout.vue` —— 侧栏 + 逃生口
- `router/index.ts` —— 路由守卫｜`stores/auth.ts` —— `auth.role` + localStorage
- `views/DevicesView.vue` —— 设备页（W7-8 回租出售按钮）｜`views/LeasingView.vue` —— 金租页（3 字段）
- `views/ProfitView.vue` —— 利润测算（UX-3 百分比兜底）｜`config/modules.ts` —— GenericCrud 8 模块配置

**后端**（`backend/app/`）
- `services/workflow_service.py` —— `_device_flow_steps` 11 步 + `get_my_tasks`
- `services/device_service.py` —— 设备状态机 + `_sync_device_asset` 权属派生（调 `derive_ownership`）+ 资产同步
- `services/billing_service.py` —— 按台计费 `generate_billing_device`（:109）
- `services/leaseback_sale_service.py` —— 售后回租出售全链路（W7-8）
- `services/leasing_service.py` —— 金租 9 节点 create_process
- `utils/ownership.py` —— `derive_ownership` 权属派生纯函数（:21）
- `utils/depreciation.py` —— 折旧 + `truncated_schedule` 截断
- `core/db.py` —— 连接池（:11，pool_size=20/max_overflow=20）
- `core/deps.py` —— `require_role`（:28）

**schema / 迁移**（⚠️ 在 `backend/` 根，非 `backend/app/`）
- `backend/db/schema.sql` + `backend/alembic/versions/0001~0008` —— schema 双写

**规格 / 计划**
- `docs/superpowers/specs/2026-08-04-siegpu-upgrade-plan.md` —— 升级总规划（权威）
- `~/.claude/plans/cheeky-hopping-shore.md` —— W7-8 实施计划（已完成）
- `docs/HANDOFF.md` —— 开发接力（⚠️ §3 W7-8 状态过时，待更新）

---

## 9. 已知坑（踩过，别再踩）

| 坑 | 规避 |
|---|---|
| Dashboard 待办卡 title 必须保「待处理」 | e2e 用 `.n-card hasText:'待处理'` 定位；角色化首页横幅文本必须避开此三字 |
| cfo 菜单别收紧 | e2e 全程用 cfo 登录，收紧会大面积回归 |
| vue-tsc 查不出模板标签错误 | 改完前端务必跑 `npm run build`（vite build 才抓 Invalid end tag） |
| e2e 写共享 dev DB 无隔离 | 历次 seed 累积污染（devices 曾达 1418），长 UI 测试加 `test.slow()` |
| schema.sql-folding | `0001_init` 执行当前 schema.sql 全文，全新库 `alembic upgrade head` 会 DuplicateColumn；验迁移用 throwaway 库往返 |
| 向导模板同源 folding | `create_workflow` 复制 DB 冻结模板，改 `_device_flow_steps` 后需 seed upsert 同步 |
| naive-ui NSelect Playwright 三坑 | placeholder 不在 input / 残留隐藏 option / 过渡动画时序（见 memory） |
| `core/db.py` 连接池扛不住全量 e2e 并发 | 已调 pool_size=20/max_overflow=20（:11） |
| **alembic check 当前 FAILED（待修）** | `invoices.billing_id` 外键 `fk_inv_billing` 漂移：库里约束带 `DEFERRABLE INITIALLY DEFERRED`、ORM 模型里没有 → autogenerate 会生成 remove_fk+add_fk 非空迁移；另有 `billings / capital_transactions / invoices` 三表外键互引成环 SAWarning。根因待查（疑似历史迁移的 DEFERRED 约束未同步进模型） |

---

> 本汇报由 2026-08-08 接力会话生成，**经逐行验证后修正**（pytest 225 实跑、W7-8 落地文件实测存在、e2e 44 实列、`alembic check` 一手复现 FAILED）。已修正：① §4 alembic「零 diff」改为实测 FAILED ② `settle_ownership` 函数名更正为 `derive_ownership` ③ `generate_billing_device` 归属 `billing_service.py:109` ④ schema.sql/db.py 路径补正 ⑤ UX-3 label 措辞精确化。后续更新请同步 `docs/HANDOFF.md`。
