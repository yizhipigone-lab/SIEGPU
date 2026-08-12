# SIEGPU ERP 开发接力（Handoff）

> **最后更新**：2026-08-12
> **最近里程碑**：二期 W1-2（EBS 业财一体化接口 Mock 骨架·出站）完成并端到端验证（pytest 262 绿 / e2e 51 绿 / 浏览器真点 :8088）
> **当前分支**：`main`　**工作区状态**：大量未提交改动（二期 W1-2 + 一期遗留未提交），**未 git commit（用户铁律：未经授权不提交）**
> **给接手者**：先读「§3 当前进度」和「§4 铁律」，再决定从哪接。二期全盘进度见 §3.3，下一棒是 W3-4 收入判定引擎。

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

# 后端测试（当前 262 条）
docker compose exec backend pytest app/tests/ -q

# 前端类型检查 + 构建（host 上有 node_modules，可直接跑）
cd frontend && npm run build          # = vue-tsc + vite build
# 注意：vue-tsc 查不出 Vue 模板标签错误，靠 vite build 才抓得到（已踩过）

# e2e（Playwright，当前 51 条；baseURL 走 :8088）
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

### 3.3 二期全局进度（7 阶段，完成 1 / 待做 6）

| 阶段 | 主题 | 新表 | 状态 |
| --- | --- | --- | --- |
| W1-2 | EBS Mock 骨架（出站） | 2 | ✅ 完成 |
| **W3-4** | 收入核算判定引擎（经营租赁/服务费/净额法/总额法/待判定 5 路径，合同 +7 字段） | 0 | ⏳ 下一棒 |
| W5-6 | 币种 + 汇率 + 汇兑损益 | 3 | ⏳ |
| W7-8 | 保险管理（设备粒度，保费分摊+摊销） | 3 | ⏳ |
| W9-10 | 合同深化 + 预付款结转 + 单据编号/金租规则（含 SN 回迁） | 4 | ⏳ |
| W11-12 | 付款三重管控 + 通用审批 + 进项税（**最复杂、滑期风险最高**） | 3 | ⏳ |
| W13-14 | 全链联调 + golden 算例 + 端到端串烧 | 0 | ⏳ |

新表进度：15 张完成 2，剩 13。**非代码待办**：W1 同步动作「发 EBS 接口规范申请函」（外部 IT/EBS 流程，Mock 按假设字段建，真规范来了映射可能返工——已接受折中）。

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

- `services/ebs_client.py` + `ebs_sync_service.py` —— 二期 EBS Mock client + 10 sync + 幂等
- `api/v1/endpoints/ebs.py` + `schemas/ebs.py` + `models/ebs.py` —— EBS REST/ORM
- `services/workflow_service.py` —— 11 步权威流程 + `get_my_tasks`（按 doer_role 派活）
- `services/device_service.py` —— 设备状态机 + 资产/off_balance 同步
- `services/report_service.py` —— 对账单（`received` 读 `paid_date IS NOT NULL`）
- `scripts/cleanup_e2e.py` —— dev-DB e2e 数据清理（globalTeardown 调）
- `db/schema.sql` + `alembic/versions/0001..0010` —— schema 双写（0010 = ebs_mock）

**规格 / 计划**

- `docs/superpowers/specs/2026-08-10-siegpu-phase2-execution-plan.md` —— **二期权威执行计划**（逐周/逐表/逐测试，含 W3-14 详细设计）
- `docs/superpowers/specs/2026-08-04-siegpu-upgrade-plan.md` —— 父计划（一期+二期总规划）

## 6. 已知坑（踩过，别再踩）

| 坑 | 说明 / 规避 |
| --- | --- |
| **宿主 :8080 是野 uvicorn，前端在 :8088** | curl/MCP 验证前端一律 :8088；判别看 `server:` header（nginx vs uvicorn）。详见 §2 |
| **改前端 restart/up 不带 --build 不生效** | nginx 构建时烤 dist，无 source mount；必须 `up -d --build frontend` |
| **pytest 绿 ≠ 生产对（autoflush 铁律）** | 生产 `SessionLocal autoflush=False`；ORM 关系字段设值后须显式 flush 才被同事务查询命中（债①根因） |
| **reconcile 与对账单不对称** | 完整核销只写 matched_amount 不写 paid_date → 不动对账单 `received`；驱动 received 用 `POST /invoices/{id}/pay`。潜在隐性 bug，二期未修，仅记 |
| **Dashboard 待办卡 title 保「待处理」** | e2e `.n-card hasText:'待处理'` 定位；横幅文本避开此三字 |
| **vue-tsc 查不出模板标签错误** | 自闭合标签多余闭合 vue-tsc 绿但 vite build 报错；改完前端跑 `npm run build` |
| **naive-ui NSelect Playwright 三坑** | placeholder 不在 input / 残留隐藏 option / 过渡动画时序；封装见 memory `naive-ui-select-playwright` |
| **e2e 写共享 dev DB 无隔离** | 历史 99 条采购待办曾压垮 `get_my_tasks`（无 LIMIT）致 wizard flake；已加 `cleanup_e2e.py` + globalTeardown 治理 |

## 7. 给下一步的建议

**下一棒：二期 W3-4 收入核算路径判定引擎**（计划 §5 W3-4，详细已就绪）。

- 合同表加 7 字段（全 nullable）：`pricing_authority` / `inventory_risk_bearer` / `principal_role` / `revenue_method` / `method_judge_basis` / `method_confirmed_by` / `method_confirmed_at`。
- 纯函数规则引擎 `utils/revenue_rules.py`（R1/R1b/R2/R3/R4 优先级命中即停），R1 已裁定用 `'经营租赁'`（D1，无阻塞）。
- `services/revenue_judge_service.py`：判定 + 落合同 + audit + EBS sync（`entity_type='contract_revenue_method'`，复用 W1-2 出站）。
- `test_revenue_judge.py` ≥8 条，**用真实枚举值造数据断言 R1 命中**（锁死 D1，防文案/枚举漂移）。
- 只判定不驱动收入确认（D5，确认属三期）。

**接手者第一件事**：跟用户确认是从 W3-4 起，还是挑别的（如先发 EBS 规范申请函、或处理工作区里那一堆未提交的 e2e/配置改动）。**不要未经确认就开新实现**（规则1：先问清楚）。

> 工作区现状提示：除二期 W1-2 改动外，还有一批一期遗留未提交的改动（多个 e2e spec 微调、`revenue-chain.spec.ts`、`docker-compose.yml` 8088 端口、`playwright.config.ts` baseURL、`e2e/fetch-doubao.js`〔来源待确认，勿盲目提交〕）。提交前先 `git status` + `git diff --stat` 评估，分类提交，别 `git add -A`。

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

> **文档版本**：2026-08-12（二期 W1-2 收口版）｜**下一状态**：W3-4 收入判定引擎（等用户拍板开工）
