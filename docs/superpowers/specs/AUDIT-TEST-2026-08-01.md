# SIEGPU ERP 测试覆盖质量审计报告

- 审计日期：2026-08-01
- 审计对象：`E:\1target\SIEGPU\backend\app\tests\`（100 个 pytest 用例）、`frontend/`（0 个单测）、`e2e/`（Playwright）
- 运行环境：docker-compose 容器内（`siegpu-backend-1`）实测
- 结论：`100 passed, 136 warnings`。审计覆盖整体合格但存在 4 个明确缺口 + 1 处空断言。

---

## 0. 现状总览

| 层 | 测试数 | 框架 | 覆盖率/状态 |
|---|---|---|---|
| 后端 pytest | 100（全部通过） | pytest 9.1.1 + 真实 PG `siegpu_test` | 服务层 0%~100% 不等（详见 §5.4） |
| 前端单测/组件测试 | **0** | **未安装任何测试框架** | 完全空白 |
| E2E | 23 个 test()（17 个 spec 文件） | Playwright 走 nginx:8080 全链路 | 含 debug 伪测试 |

100 个 pytest 用例分布：

| 文件 | 用例数 | 质量评级 |
|---|---|---|
| test_algorithms.py | 17 | 优（纯函数 + 审计黄金值） |
| test_audit_log.py | 7 | 优（强断言，"审计留痕"） |
| test_audit_service.py | 8 | **中（弱断言，"新增 8 条"）** |
| test_capital_service.py | 9 | 优 |
| test_workflow_service.py | 7 | 良（耦合内部 step JSON） |
| test_master_service.py | 7 | 良 |
| test_leasing_service.py | 6 | 优 |
| test_acceptance_service.py | 6 | 良 |
| test_query_endpoints.py | 6 | 良 |
| test_billing_invoice_service.py | 5 | 良 |
| test_funding_service.py | 5 | 良 |
| test_repayment_service.py | 2 | 良 |
| 其余 4 文件 | 13 | — |

---

## 1. 核心问题：新增 8 条审计测试对 10 类审计动作的覆盖

"新增 8 条" = `backend/app/tests/test_audit_service.py`（恰好 8 个测试函数）。

### 10 类审计动作 × 8 条新测试覆盖矩阵

| # | 动作 | 写入位置 | 8 条新测试中 | 断言强度 | 全库是否有强断言 |
|---|---|---|---|---|---|
| 1 | CAPITAL_TXN | capital_service.py:169 | `test_audit_capital_txn`:26 | 弱（`len>=1`+user_id，无 entity_id/after_json） | **否 — 仅此弱断言** |
| 2 | DISBURSE | leasing_service.py:147 | `test_audit_disburse`:44 | 弱（`len>=1`） | 是（test_audit_log.py:37） |
| 3 | SUPERSEDE | leasing_service.py:126 | `test_audit_disburse`:61 | **空断言（恒真）** | 是（test_audit_log.py:37） |
| 4 | LIGHT_ON | order_service.py:103 | `test_audit_light_on`:66 | 弱（`len>=1`+user_id） | 是（test_audit_log.py:124） |
| 5 | ACCEPT_APPROVE | acceptance_service.py:68 | `test_audit_accept_approve`:87 | 弱（`len>=1`） | 是（test_audit_log.py:109） |
| 6 | REVERSE | invoice_service.py:112 / capital_service.py:265 | `test_audit_reverse_invoice`:104 | 弱（`len>=1`，filter invoice） | 是（capital 路径 test_audit_log.py:78） |
| 7 | ALLOCATE | capital_service.py:225 | `test_audit_allocate`:119 | 弱（`len>=1`） | 是（test_audit_log.py:91） |
| 8 | RECONCILE | invoice_service.py:180 | `test_audit_reconcile`:135 | 弱（`len>=1`） | 是（test_audit_log.py:61） |
| 9 | CONFIRM_UPLOAD | confirmation_service.py:64 | `test_audit_confirm_upload`:159 | 弱（`len>=1`） | **否 — 仅此弱断言** |
| 10 | ALLOCATE_RETURN | capital_service.py:294 | **完全缺失** | — | 是（test_audit_log.py:91） |

### 结论

- **仅看 8 条新测试**：只覆盖 10 类中的 **8 类**。`ALLOCATE_RETURN` 完全没有；`SUPERSEDE` 的 `assert logs_s is not None`（test_audit_service.py:63）是恒真断言——`.all()` 永远返回 list 不返回 None，无论是否写入都通过，属于"断言过少"反模式。
- **看全库**：10 类动作全部有至少一条强断言（因为 `test_audit_log.py` 已用强断言覆盖 8 类）。但 **CAPITAL_TXN 和 CONFIRM_UPLOAD 在整套测试里都只有弱断言**——若 confirmation_service.py / capital_service.py 的审计写入被删或写错字段，`len>=1` 仍然会过。

> 关键事实：`test_audit_log.py`（旧）比 `test_audit_service.py`（新增 8 条）断言更严。新 8 条是对旧测试的**重复覆盖但降级**：同样的 DISBURSE/REVERSE/ALLOCATE/RECONCILE 旧文件已强断言，新文件反而只 `len>=1`。唯一新增价值是 CAPITAL_TXN 与 CONFIRM_UPLOAD 两个动作（其余为冗余弱测）。

---

## 2. 缺少的审计动作测试

1. **ALLOCATE_RETURN**（8 条新测试中缺失）— 已在 `test_audit_log.py:91-105` 强断言（`len(rt)==1` + `entity_type=="capital_allocation"` + `after_json["return_date"]`），无需再补，但新 8 条声称"覆盖 10 类"不成立。
2. **CONFIRM_UPLOAD**（全库仅弱断言）— `test_audit_service.py:159` 只 `len>=1`，没有校验 `entity_type=="service_confirmation"`、`entity_id==sc.id`、`after_json["customer"]`。
3. **CAPITAL_TXN**（全库仅弱断言）— `test_audit_service.py:26` 只 `len>=1`+`user_id`，没校验 `after_json.source_type/direction/amount`（capital_service.py:170-171 实际写入这些字段）。
4. **SUPERSEDE 空断言** — test_audit_service.py:63 `assert logs_s is not None` 应删除或改为造 流贷付款 后 `len>=1`（test_audit_log.py:37 是正确范本）。

---

## 3. 脆性测试（过度依赖实现细节）

**评级：中等。整体 100 个用例偏健壮，但有 3 类问题。**

### 3.1 空断言 / 恒真断言（P1）
- `test_audit_service.py:63`：`assert logs_s is not None` — 恒真，给 SUPERSEDE 制造"已覆盖"的假象。反模式"断言过少"。

### 3.2 after_json 字符串格式耦合（P2）
`test_audit_log.py` 多处断言审计 JSON 的字符串值，依赖 service 用 `str(Decimal)` 序列化：
- :55 `after_json["amount"] == "600000"`（DISBURSE）
- :57 `after_json["amount"] == "300000.00"`（SUPERSEDE）
- :74 `after_json["matched"] == "100000.00"`（RECONCILE）
- :87 `after_json["amount"] == "80000"`（REVERSE）
- :103-105 `after_json["amount"] == "200000"` / `return_date == "2026-02-01"`（ALLOCATE/ALLOCATE_RETURN）

风险：任一 service 把 `str(txn.amount)` 改成 `float()` 或 `"600000.00"` 格式即碎。**这些断言捕捉真实审计内容（有价值），但耦合了 Decimal→str 的实现细节**。建议弱化为"值相等"（`Decimal` 比对）或仅在审计契约变更时同步更新。

### 3.3 工作流引擎内部 step JSON 结构耦合（P2）
`test_workflow_service.py` 直接读内部 JSON 结构：
- :41-43 `_step(wf, seq)` 遍历 `wf.steps` 按 `s["seq"]` 取步骤
- :101-104 断言 `s["status"] == "done"` 推进状态
- :123-124 `step12["completion_check"]["table"] == "delivery_stages"` / `step14["completion_check"]["table"] == "orders"` — 直接钉死 workflow_template 内部 `completion_check` 配置

风险：工作流模板/引擎重构 step schema 即碎。但这些是引擎的真实契约，属于"测试了实际行为"，脆性可接受，仅在模板结构变更时需同步。

### 3.4 非脆性确认
- `test_algorithms.py` 的黄金值（如 `D("53333.33")`、`D("15000.00")`）是**有审计依据的验算值**（docstring 注明"复审 NW2 验算"），不是脆性魔法数。
- 全库仅 1 处 monkeypatch（test_workflow_service.py:146-157），用于异常兜底回归测试，用法正确。

---

## 4. 测试隔离

**评级：优。隔离设计正确，无共享状态污染。**

- `conftest.py:40-48`：函数级 `db` fixture = 每用例独立 connection + `trans.rollback()`，用例间完全隔离。
- `conftest.py:33-37`：session 级 `engine`，每 session 重建一次 schema。
- 所有用例用 `uuid.uuid4().hex[:6]` 生成唯一 username/code，即使回滚逻辑有漏洞也不会撞唯一约束。
- `audit_service.py:35-36` 审计写入不 flush，依赖调用方 flush；而 SQLAlchemy 默认 `autoflush=True`，SELECT 前自动 flush 待写对象，故 `db.execute(select(AuditLog))` 能查到，无坑。

**两个环境性隐患（非测试代码 bug）：**
1. **只能 Docker 内跑**：`conftest.py:10` 默认 URL 指向 `db:5432`，`:28` 硬编码 `/app/db/schema.sql`（容器路径）。裸机无 Docker 跑不了，也改不了测试库指向。可加 `.env`/`TEST_DB_*` 覆盖 + `Path(__file__)` 相对定位 schema.sql 提升可移植性。
2. **禁开 pytest-xdist**：session 级 `_ensure_test_db` 的 `DROP SCHEMA CASCADE` 与并行事务不兼容。当前单进程 OK。

---

## 5. 前端组件测试覆盖

**评级：完全空白（最大结构性缺口）。**

- `frontend/package.json` 无任何测试脚本；devDependencies 只有 vite/typescript/vue-tsc，无 vitest/jest/@vue/test-utils/testing-library。
- `frontend/src` 35+ 源文件（12 组件 / 15 视图 / 4 utils / 1 composable / 1 store / 1 router）**零单测**。
- 唯一 UI 验证是 e2e/ 的 Playwright 黑盒（走 nginx:8080 全链路），**不覆盖组件内部逻辑，也不覆盖 utils**。

### 5.1 应补单测的纯函数（当前 0 覆盖）
- `src/utils/format.ts`：`money`（null/''/NaN/边界）、`tsToYmd`（时区/非法时间戳）、`ymdToTs`（非法日期）、`statusTagType`（未匹配 fallback）— 4 个纯函数
- `src/utils/role.ts`：`roleName`（null→'—'、未知代码原样）
- `src/utils/errMsg.ts`、`src/composables/useResource.ts`

### 5.2 应补组件测试的共享组件
- `GenericCrud.vue`（通用 CRUD 表）、`StepDrawer.vue`、`step-forms/*`（CapitalForm/InvoiceForm/ConfirmationForm 等）— 提交前单位/日期转换逻辑，是 2026-07-20 那类"前端 /100"转换 bug 的高危区。

### 5.3 后端覆盖率缺口（pytest --cov 实测）

| 服务 | 覆盖率 | 关键未覆盖行 |
|---|---|---|
| profit_service.py | **23%** | 38-52, 58-140, 159-215, 237-242（场景测算核心逻辑） |
| confirmation_service.py | 61% | 17-22, 34, 39-46, **76-82（dispute 有争议路径）**, 54 |
| workflow_service.py | 61% | 106-134, **207-241（skip 路径）**, **332-342, 349-386（状态流转/手工完成）** |
| sales_order_service.py | 52% | 29, 33-38, 42-46 |
| workflow_template_service.py / ocr_service.py / project_service.py | **0%** | 全部 |
| **全部 API endpoints** | **0%** | acceptances/capital/invoices/leasing 等 26 个文件 |

API 层 0% 是最值得注意的：查询端点有 service 级测试（test_query_endpoints.py），但**没有一条走 HTTP 层（FastAPI TestClient）的端点测试**——审计闭环在 API 边界（鉴权、请求校验、审计写入触发）没有验证。

---

## 6. 需补测试的优先级清单

| 优先级 | 项 | 现状 | 建议 |
|---|---|---|---|
| **P0** | CONFIRM_UPLOAD 强断言 | 全库仅 `len>=1`（test_audit_service.py:159） | 补 `entity_type=="service_confirmation"`、`entity_id==sc.id`、`after_json["customer"]`；5 分钟 |
| **P0** | CAPITAL_TXN 强断言 | 全库仅 `len>=1`+user_id（test_audit_service.py:26） | 补 `entity_type=="capital_transaction"` + `after_json.source_type/direction/amount`；5 分钟 |
| **P0** | SUPERSEDE 空断言 | test_audit_service.py:63 恒真 | 删除该断言，或先造 流贷付款 再 `len>=1`（照抄 test_audit_log.py:37）；或直接删弱测，靠 test_audit_log.py 覆盖 |
| **P1** | 前端单测基础设施 + utils | 0 覆盖 | 装 vitest + @vue/test-utils；先测 format.ts / role.ts（含 null/NaN/非法日期边界）；半天 |
| **P1** | GenericCrud / StepDrawer 组件测试 | 0 覆盖 | 组件交互 + 表单单位/日期转换；1 天 |
| **P2** | profit_service.py 场景测算 | 23% | 补 IRR/NPV/利润测算与 save_scenario 全分支；1 天 |
| **P2** | workflow_service.py skip/流转路径 | 61% | 补 skip_step、状态回退、手工 mark_done 分支；半天 |
| **P2** | confirmation_service.py dispute 路径 | 61% | 补"有争议"标记分支；30 分钟 |
| **P3** | API 端点集成测试 | 0% | 用 FastAPI TestClient 至少覆盖审计相关端点：POST capital/transactions、leasing/disburse、invoices/reverse、confirmations/confirm、allocations/return；1-2 天 |
| **P3** | e2e 清理 | 17 spec 含 debug 伪测 | 删/隔离 `debug-crud`、`debug-login`、`repro-404`、`screenshots`、`audit2`，CI 只跑 `verify-*` + `wizard-workspace` + `capital-flow` |

---

## 附：10 类审计动作的日志写入位置（供复核）

| 动作 | 文件:行 | after_json 内容 |
|---|---|---|
| CAPITAL_TXN | capital_service.py:169-171 | source_type, direction, amount |
| DISBURSE | leasing_service.py:147-148 | amount, periods |
| SUPERSEDE | leasing_service.py:126-127 | amount, source |
| LIGHT_ON | order_service.py:103 | date |
| ACCEPT_APPROVE | acceptance_service.py:68 | status |
| REVERSE | invoice_service.py:112 / capital_service.py:265 | amount |
| ALLOCATE | capital_service.py:225 | amount |
| RECONCILE | invoice_service.py:180 | matched |
| CONFIRM_UPLOAD | confirmation_service.py:64-65 | customer |
| ALLOCATE_RETURN | capital_service.py:294 | return_date |

---

**审计方法说明**：所有结论基于在 `siegpu-backend-1` 容器内实测 `python -m pytest app/tests/ -q --cov=app --cov-report=term-missing`（100 passed）+ 逐一 Read 测试/服务源码 + git log（单提交 f96b061，无法追溯"8 条新增"历史，按 test_audit_service.py 恰好 8 个函数认定）。
