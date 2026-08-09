# SIEGPU 算力租赁 ERP — 一期终审报告（2026-08-09）

> 续 [WORK-REPORT-2026-08-09-小白友好与功能补全.md](WORK-REPORT-2026-08-09-小白友好与功能补全.md) §7.3「W9-10 联调回归 + 一期终审」。
> 本文是一期（Phase 1）的终审判定书：做了什么、绿了什么、欠了什么、能不能收。

---

## 0. 终审判定（结论先说）

**一期功能闭环、回归网到位、数据准确性债①已修，判定为「可收」。**

- ✅ **功能**：一期范围（W1-2 设备层 + W3-4 + W5-6 按台计费 + W7-8 金租/售后回租 + 小白友好 8 项）全部落地。
- ✅ **回归网**：e2e **50**（49 稳定绿 + 1 纯核销回归；devices 首行 flake 见 §3 债③，预先存在非本次回归），含「营收全链路串烧」一条 journey，第一次把赚钱链路从立项到回款串成一条端到端用例——一条绿 = 整条链没断。
- ✅ **1 个高优先级数据准确性债已修复（债①）**：发票核销（reconcile）不写 `paid_date` → 对账单「已回款」漏计纯核销；**更深一层根因**——reconcile 设 `txn.invoice_id` 后未显式 `flush` 就查 matched，生产 session（`SessionLocal autoflush=False`）下 matched 恒为 0 → 全核销分支根本进不去（不只漏 paid_date，连「已核销」都标不上）。已修 + 3 条 pytest 回归 + 1 条纯核销 e2e 验证（详见 §4-债①）。
- ⚠️ 3 个稳定性/UX 债（对账单加载竞态、devices e2e 首行 flake、待办查询无分页）可列入一期后加固，不阻断收口。

> 给非技术读者的翻译：这套系统「能赚钱的整条流程」我们已经从头到尾在浏览器里真点过一遍、数字对得上。之前发现**一个**会影响「客户欠我们多少钱」这张表的账务毛病（「核销发票」操作可能让已回款少算一笔），**现已修好并端到端验证通过**。剩下三个小毛病是体验和测试稳定性的，不急。

---

## 1. 终审范围与方法

一期终审分两步（Step 1 上一轮已完成，Step 2 本轮完成）：

| 步 | 内容 | 产出 |
|---|---|---|
| Step 1 | 给 F2/F3/F4/F1 各补正向 e2e journey + 治理 dev-DB 测试数据污染 | `e2e/tests/w9_final_audit.spec.ts`（4 journey）+ `cleanup_e2e.py` + `global-teardown.ts` → 全套 48/48 |
| Step 2 | 写**一条**把营收全链路串成单一 journey 的 e2e，专捕跨模块集成回归 | `e2e/tests/revenue-chain.spec.ts`（1 journey）→ 全套 49/49 |

**方法铁律**：端到端验证（后端跑通不算完，浏览器真点验到才算）+ 追值法（断言用的金额一律从创建响应读真值，不手算）+ 验证不猜测（每条结论读码/实测，引用 file:line）。

---

## 2. Step 2 交付物：营收全链路串烧 —— 为什么它是「一期最后一道网」

### 痛点（为什么写它）
一期 22 个原有 e2e 里，每个营收模块都只被**孤立**测试。没有任何一条用例把「立项→销售合同→采购→设备点亮→计费→开票→回款→对账单」串成一条 journey。两个最危险的空白：
- **回款（`/pay`）从未被任何 e2e 触发**——整条链最后一步、最影响「钱到没到」的一步，之前零覆盖。
- **客户对账单只验过全零场景**（Step 1 的 F3）——四 KPI 勾稽在有真实计费/开票/回款时对不对，没人验过。

> 金租/回租/折旧已被 `w5_6`/`w7_8` 充分覆盖，不串进来（避免重复 + 巨脆）。

### Journey 设计（9 跳 API 造数 + 追值法断言 + UI 收口）
一条连续用例，全 `cfo`（FINANCE_DIRECTOR）账号：

```
立项 → 销售合同(100万) → 客户 → 设备型号 → 采购订单 → 设备(monthly_price=10万)
  → 推进到点亮验收(2026-09-01 月初=整月计费)
  → 按台计费 period1  → 捕获 B = amount_ex_tax = 88,495.58
  → 开票(含税6万)      → 捕获 I = amount_ex_tax = 53,097.35   ← 故意 ≠ B，辨析 billed/invoiced 混淆
  → 回款 /pay(2026-09-25)
  → 读客户对账单，四 KPI 勾稽（追值法）→ UI 浏览器看对账单渲染
```

**追值法断言**（B、I 从创建响应读真值，再读对账单回传校验）：

| 对账单字段 | 期望 | 实测 | 判别力 |
|---|---|---|---|
| `contract_amount` | 1,000,000（不含税原值） | ✅ | 链起点没断。合同额本就不含税（与 billed 同口径），`gap_unbilled` 相减不混税基 |
| `billed`（已计费） | = B = 88,495.58 | ✅ | 计费→对账单没断 |
| `invoiced`（已开票） | = I = 53,097.35 | ✅ | 开票→对账单没断 |
| `received`（已回款） | = I（/pay 后） | ✅ | **回款→对账单没断（首覆盖）** |
| `gap_uncollected` | = invoiced − received = 0 | ✅ | ex-tax 口径自洽 |
| 流水明细 | 含计费行 88,495.58 + 回款行 53,097.35 | ✅（UI） | 端到端可见 |

> 故意让 B(88,495) ≠ I(53,097) ≠ 合同额(1,000,000)，三者不等的关系链能抓「计费/开票/回款混淆」「聚合漏行」「paid_date 没置上」等回归——比「都填同一个数」的弱断言强得多。

### 自检迭代（写完不是终点，挑自己漏洞）
1. **cleanup 前缀泄漏**（自检修）：初稿客户用 `客户-串烧-`、型号用 `M-串烧-`，读 `cleanup_e2e.py` 正则发现这俩**无 `project_id` 不走级联**、且前缀对不上独立判据 → 会残留污染共享库。改 `客户-E2E-串烧-` / `E2E-型号-串烧-`，跑完 teardown 确认全清。
2. **UI 等待时序**（自检修）：组件无 loading 标志，并行负载下对账单查询数秒，`stmt` 慢时仍显示上一客户旧值。曾用 `waitForResponse` 钉 URL，但谓词偶发不匹配（响应到了却没命中，30s 超时）→ 改 `toBeVisible(money(B), 30s)` 直接验渲染，更稳也更贴合端到端铁律。

---

## 3. 验证证据（绿数）

| 项 | 结果 | 备注 |
|---|---|---|
| **e2e 全套** | **50（48 绿 + 1 已知 flake + 1 级联跳过）** | 49（Step 1/2 基线）+ 1（pure-reconcile 债①回归）。⚠️ **非稳定绿**：devices.spec.ts「批量推进」全套并发下 ~50% flake（债③，预先存在、非本次回归），同文件 serial 级联跳过「单台推进」；50 全绿是「最佳可达」非「每次必绿」 |
| e2e 单跑 pure-reconcile | 1/1 绿（4.7s） | 债①回归：纯核销（不经 /pay）→ 对账单已回款反映，含 UI 收口 + teardown 闭环 |
| e2e 单跑 revenue-chain | 1/1 绿（4.9s） | 含 teardown 闭环；串烧本身稳定绿 |
| teardown 数据闭环 | ✅ | 每跑清掉本轮造的客户/型号/合同/设备/计费/发票，dev-DB 不堆积 |
| 后端 pytest | **249 全绿（已复跑确认）** | 246 基线 + 3（债①回归：纯核销全额写 paid_date / 部分核销不写 / 不覆盖 /pay 的 paid_date） |

**复现命令**：
```bash
cd e2e && npm test                                           # 全套 e2e（49 + pure-reconcile = 50，devices flake 见债③）
cd e2e && npx playwright test tests/pure-reconcile.spec.ts   # 单跑债①纯核销回归
cd e2e && npx playwright test tests/revenue-chain.spec.ts    # 单跑串烧
docker compose exec backend pytest app/tests/ -q             # 后端 249（含 3 条债①回归）
```

---

## 4. 设计债清单（终审新发现 + 已知，按优先级）

### ✅ 债①（高 · 数据准确性，已修复 + 端到端验证）：核销不写 paid_date → 对账单「已回款」漏计（根因更深：全核销分支在生产 session 下根本进不去）
- **原现象**：客户对账单「已回款」用 `Invoice.paid_date IS NOT NULL` 判定（[report_service.py:156](backend/app/services/report_service.py#L156)、[test_customer_statement.py:5](backend/app/tests/test_customer_statement.py#L5) 明确「用 paid_date 判定回款」）。但**逐笔核销** `reconcile_invoice`（[invoice_service.py:134-193](backend/app/services/invoice_service.py#L134-L193)）只写 `status=已核销`/`reconciled_at`/`reconciled_by`，**不写 `paid_date`**。
- **挖出的更深根因（验证不猜测，读码 + e2e 实测）**：漏写 paid_date 只是表症。补上 paid_date 后跑纯核销 e2e，发现 status 仍是「已开」、全核销分支**根本没进入**——读码定位到 `reconcile_invoice` 设 `txn.invoice_id = inv.id` 后**立即**跑 matched 聚合查询、中间无显式 `db.flush()`，依赖 SQLAlchemy autoflush。而生产 `SessionLocal` 是 `autoflush=False`（[db.py:13](backend/app/core/db.py#L13)），不刷则查询读到 `invoice_id=NULL` 旧值 → **matched 恒为 0 → 全核销分支永不进入**（不只漏 paid_date，连「已核销」都标不上）。pytest 一直绿，是因为 conftest 的 db fixture 走默认 `Session(autoflush=True)`（[conftest.py:44](backend/app/tests/conftest.py#L44)）会隐式刷掉 UPDATE → **autoflush 差异把生产 bug 藏在 pytest 全绿背后，最终由纯核销 e2e 揪出**。
- **修复（[invoice_service.py:163-182](backend/app/services/invoice_service.py#L163-L182)）**：① 设 `txn.invoice_id` 后、matched 查询前补**显式 `db.flush()`**（根因修复——不依赖 autoflush 做「写入后立即查」的正确性）；② 全核销分支补 `if inv.paid_date is None: inv.paid_date = txn.transaction_date`（`is None` 守卫不覆盖工作流 pay→reconcile 已置的 paid_date，零回归）。已 grep 确认 services 内「设 FK→立即聚合」危险模式仅此一处，无同源隐患。
- **验证**：3 条 pytest 回归（全额→paid_date=流水到账日且对账单 received 反映 / 部分核销→不写 / 不覆盖 /pay 的 paid_date）+ 1 条纯核销 e2e（建收款流水→直接核销不经 /pay→断言对账单 received==开票额、流水明细含「回款」行、cfo 浏览器看渲染）。pytest **249 全绿**、e2e 单跑 **1/1 绿**、全套 **0 回归**。
- **教训（autoflush 铁律）**：「service 层 pytest 全绿」≠「生产路径正确」——pytest 的 `Session(autoflush=True)` 与生产的 `SessionLocal(autoflush=False)` 配置不同，凡「改对象属性后立即查」的代码都可能在 pytest 绿、生产红。**显式 flush 才是生产可靠写法；此类回归只能靠 e2e（真实生产 session）兜住**。这是端到端验证铁律又一例证（继 W3-4 OrderDetail 500、billing 闸错位之后）。

### ✅ 复核排除（曾误判为 🔴 债②「对账单未计费税基混用」，实为假阳性）
- **初判（误）**：审计一度认为 `gap_unbilled = contract_amount − billed`（[report_service.py:218](backend/app/services/report_service.py#L218)）把含税合同额减不含税计费、混了税基，列为比债①更基础的 🔴 高债。
- **复核结论（6 点证据，Contract.amount 设计上即不含税 → 不混税基）**：开始修前按「验证不猜测」读码核实，**推翻**上述判定——
  1. 合同创建表单 label 明写 **`合同金额(不含税,元)`**（[modules.ts:157](frontend/src/config/modules.ts#L157)）；
  2. 术语表注释 **`金额：本表单里指不含税金额（元）`**（[glossary.ts:20](frontend/src/utils/glossary.ts#L20)）；
  3. 测试注释 **`合同不含税 1000`**（[test_billing_invoice_service.py:57](backend/app/tests/test_billing_invoice_service.py#L57)）；
  4. report_service docstring 自称「全部用不含税口径」且**成立**（[:139](backend/app/services/report_service.py#L139)）；
  5. `test_customer_statement.py` 把 `contract_amount=3000` 与不含税 `billed=2300` 当同口径相减、断言 `gap_unbilled=700`；
  6. 前端列标题 `合同额(不含税)`（[CustomerStatementView.vue:51](frontend/src/views/CustomerStatementView.vue#L51)）渲染的就是不含税 `c.amount`，label 与数据一致。
  → `gap_unbilled = c.amount(不含税) − billed(不含税)` **同口径相减，正确**；对账单「未计费」常驻字段**不失真**，无需修。用户亦已确认销售按不含税录入。
- **教训**：把「合同金额」想当然当含税、没查录入表单 label 就定性为 🔴，是审计假阳性。revenue-chain.spec.ts:135-137 注释里「混了税基」的说法同样错误，已一并纠正。

---

### 🟡 债②（中 · 前端竞态/UX）：客户对账单加载重入 + 无 loading 标志
- **现象**：`CustomerStatementView` 的 `onMounted` 里 `loadCustomers()` 设 `selectedId` 触发 watch 的 `loadStatement()`，又**显式再调一次**（[CustomerStatementView.vue:46-47](frontend/src/views/CustomerStatementView.vue#L46-L47)）→ 同一客户两笔并发请求；组件**无 loading 标志**，`loadStatement` 慢时 `stmt` 仍显示**上一客户旧值**（本次 e2e 全套负载下实测：旧值停留 + 转圈数秒）。
- **后果**：弱竞态（后发先至可短暂覆盖）+ 切客户时短暂显示旧客户数据，体验困惑；e2e 需靠长 timeout 兜底。
- **建议修法**：加 loading 态；`loadStatement` 用请求序号/AbortController 防重入覆盖（后发先至丢弃旧响应）。

### 🟡 债③（中 · e2e 稳定性）：devices.spec.ts「批量推进」首行假设 flake
- **现象**：`createDeviceViaUI` 假设「新建设备 created_at 最新→排首行」，靠「首行内容变化」判断新建成功（[devices.spec.ts:67-84](e2e/tests/devices.spec.ts#L67-L84)）。但**并发 worker 都在造设备**（revenue-chain/w5_6/w7_8），并发设备 created_at 更新时挤掉它的首行 → 它推进了别人的设备 → 断言失败。全套 3 跑挂 2 次（~50%）。
- **定性**：**预先存在的首行反模式**（与 99 条待办同源），**非 revenue-chain 引入**（实测：devices 单跑 6/6、与 revenue-chain 并发 7/7，均绿；仅全套并发负载下偶发）。
- **建议修法**：`createDeviceViaUI` 返回新设备 SN，后续按 SN scope 定位行（不靠「首行」）；或列表先按本测试专属项目/型号过滤。

### 🟡 债④（已知 · 治标已做，治本未做）：首页待办查询无分页 + 前端吞错
- 详见 [WORK-REPORT-2026-08-09-小白友好与功能补全.md §7.2](WORK-REPORT-2026-08-09-小白友好与功能补全.md)。`get_my_tasks`（[workflow_service.py:116](backend/app/services/workflow_service.py#L116)）无 LIMIT，前端 `Dashboard.vue` 把失败/超时吞成空列表。
- **治标已做**：`cleanup_e2e.py` + `global-teardown.ts` 勤倒垃圾，防堆积复发。
- **治本未做（建议排期）**：加 LIMIT/分页 + 前端失败不吞错。

### 其余已知小债（不阻断，见上一报 §7.2）
F1 jobstore 内存重启丢未读、F4 PDF 无模板自定义、设备租赁到期用合同到期覆盖。

---

## 5. 一期能否收（判定细则）

| 维度 | 判定 | 依据 |
|---|---|---|
| 功能完整度 | ✅ 达标 | 一期范围全落地，e2e 覆盖关键路径含全链路串烧 |
| 集成正确性 | ✅ 达标 | 营收全链路 A→Z 串烧 49/49 绿，跨模块数据流验证 |
| 数据准确性 | ✅ 达标 | 债①（核销漏计已回款 + 更深的 flush 根因）**已修 + 端到端验证**（pytest 249 / e2e 50） |
| 测试稳定性 | ⚠️ 有条件 | 债③ devices flake ~50%（不阻断功能，但套件非稳定绿）|
| 回归网 | ✅ 达标 | 每模块孤立 + 全链路串烧双重覆盖，回款/对账单首次覆盖 |

**结论**：一期**可收**（能跑通、链路不断、回归网到位、数据准确性债①已修并验证）。**唯一阻断项（债①）已消除**；**债②/③/④** 列入一期后第一波加固（测试稳定性/UX，不阻断收口）。

---

## 6. 本期新增/修改文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| [backend/app/services/invoice_service.py](../backend/app/services/invoice_service.py) | 修改 | 债①修复：reconcile_invoice 设 `txn.invoice_id` 后补显式 `db.flush()`（根因——autoflush=False 下 matched 恒 0）+ 全核销分支写 `paid_date`（`is None` 守卫零回归） |
| [backend/app/tests/test_billing_invoice_service.py](../backend/app/tests/test_billing_invoice_service.py) | 修改 | 债① pytest 回归 3 条（全额写 / 部分不写 / 不覆盖 /pay 的 paid_date） |
| [e2e/tests/pure-reconcile.spec.ts](../e2e/tests/pure-reconcile.spec.ts) | 新增 | 债①纯核销 e2e（不经 /pay，对账单已回款反映，含 cfo 浏览器 UI 收口） |
| [e2e/tests/revenue-chain.spec.ts](../e2e/tests/revenue-chain.spec.ts) | 修改 | 纠正注释里已被推翻的「含税/混税基」说法（假阳性债②遗留） |
| [docs/WORK-REPORT-2026-08-09-一期终审.md](WORK-REPORT-2026-08-09-一期终审.md) | 修改 | 债①从「未修 🔴」改判「已修 ✅」+ 判定从「有条件可收」升「可收」 |

> 本次债①修复**改了后端服务代码 1 处**（invoice_service.py，含根因 flush + paid_date），其余为测试 + 报告。Step 1 的 `cleanup_e2e.py` / `global-teardown.ts` / `w9_final_audit.spec.ts` 见上一报。

---

## 7. 账号速查（e2e/手测用）

| 账号 | 角色 | 密码 |
|---|---|---|
| `cfo` | FINANCE_DIRECTOR（菜单全开，e2e 惯用） | `sie123` |
| `finance` | FINANCE_STAFF | `sie123` |
| `delivery` | 项目交付负责人 | `sie123` |

其余见 [OPERATION-GUIDE.md](OPERATION-GUIDE.md)。
