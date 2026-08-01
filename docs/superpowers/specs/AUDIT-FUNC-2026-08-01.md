# SIEGPU 安全审计 + 多项目功能模块 — 功能正确性审计报告

> 审计日期：2026-08-01
> 审计范围：审计日志写入、资金池分项目视图、项目组合总览、项目对比、预警规则
> 审计方法：读真实代码验证（backend service/endpoint/model + frontend view + design spec 交叉比对），逐条引用 file:line
> 结论分类：CRITICAL / HIGH / MEDIUM / LOW，附 PASS 项

---

## 0. 结论摘要

| Severity | Count | 关键结论 |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 3 | 资金池置换方向致净头寸虚增；回款率分子含应付发票；逾期笔数恒 0 |
| MEDIUM | 4 | 验收驳回无审计；分项目 Tab 缺闲置/缺口标识；2 条预警规则失效/不完整 |
| LOW | 4 | 审计时序先于 after_action（等价）；"逾期"状态无写入路径；停滞天数边界；缺边界用例测试 |

**Verdict: WARNING — 3 个 HIGH 影响 P1 核心交付（资金池/对比表）数值正确性，建议合并前修复。**

7 项审计重点逐条结论：
1. 审计日志写入时机 — **PASS**（全部在业务 flush 之后、同事务原子提交）
2. pool-by-project 净头寸/可调余额/在途调配 — **FAIL**（净头寸/可调余额被置换归还 IN 双计虚增）
3. portfolio 停滞天数计算 — **PASS**
4. project-comparison 回款率/IRR — **FAIL**（回款率含应付发票；IRR 提取正确；逾期笔数恒 0）
5. 4 条预警规则触发条件 — **WARNING**（3 条匹配，交付卡住只覆盖"进行中"）
6. 分项目 Tab 前后端对应 — **PASS**（字段全对应，缺"闲置/缺口"可视化标识）
7. 组合总览/对比表列定义 vs 后端字段 — **PASS**（字段全对应）

---

## 1. HIGH 发现

### H1. 资金池置换归还方向错误 → 池余额 / 分项目净头寸 / 可调余额 双计虚增
**File: backend/app/services/funding_service.py:51-63**（置换归还流水 direction="IN"）

**Issue:** 金租放款置换时，execute_replacement 生成 CapitalTransaction(direction="IN", source_type="归还流贷"/"归还自有")。同笔 8.3 亿被计两次：金租放款入金 IN + 置换归还 IN。置换归还语义是"归还垫付"（归还流贷/自有），现金方向应为 OUT（偿还垫付方），记 IN 使项目池虚增 2 倍放款额。

**Evidence（demo.py 商机5090 实测推演）:**
- 流水：IN = 流贷5.81亿 + 自有2.49亿 + 金租8.30亿 + 归还8.30亿 + 租金0.22亿 = 25.1亿；OUT = 预付采购8.30亿 -> 池余额 = 16.8亿（capital_service.pool_summary 同样算法）
- 正确现金口径：IN(16.82亿) - OUT(采购8.30亿 + 归还垫付8.30亿) = 约 0.22亿
- 虚增约 16.6 亿，直接放大 pool_by_project 的 net_position 与 allocatable（capital_service.py:50-58, 91-96），并放大预警 POOL_INSUFFICIENT 的余额基数（alert_service.py:70-75）

**影响:** P1 核心目标"哪个项目钱闲、可调出多少"失真——财务看到 16.8 亿可调出，实际可用现金约 0.2 亿，可能据此发起无法兑现的跨项目调配。

**备注:** v3.1 设计 §2.2 亦明文规定置换归还记 IN（docs/.../2026-08-01-siegpu-erp-design-v3.md），为设计级错误带入代码；v3.1 审计已标 MEDIUM（A4"余额逻辑需确认"）未修复。

**Fix:** 二选一——(a) 置换归还改为 direction="OUT"（偿还垫付方，池余额归 0.22 亿口径）；(b) 若坚持 IN 作采购冲销，则需在净额计算中排除被置换付款（is_replaced=True 的原 OUT）或单独扣除放款额，避免双计。改后补含置换的 test_pool_by_project 用例。

---

### H2. 项目对比回款率分子把"应付（采购发票已付款）"算作"已收款"
**File: backend/app/services/report_service.py:90-95**

**Issue:** received 查询取该项目所有合同（销售+采购）下 paid_date IS NOT NULL 的发票金额，未按 direction=="RECEIVABLE" 过滤。采购发票（PAYABLE）付款后 paid_date 被置（invoice_service.mark_paid），被误计入"已收款"分子。

**Evidence（demo 商机5090）:**
- billed（应收/计费）= 3 期租金 约 0.65 亿（Billing.amount，report_service.py:86-89）
- received = 销售票 SI-2026-07 0.22 亿 + 采购票 PI-001 8.30 亿 = 8.52 亿
- collection_rate = 8.52 / 0.65 约 1310%（前端 ComparisonView.vue:57 标注"回款率 = 已收款 / 应收(计费)"，明显违背语义）

**Fix:** received 查询追加 Invoice.direction == "RECEIVABLE" 条件。现有测试（test_query_endpoints.py:78-90）只覆盖"无计费、无已付款发票"场景，未覆盖该分支，故未暴露。
---

### H3. 项目对比"逾期笔数"恒为 0（无代码将 Repayment.status 置为"逾期"）
**File: backend/app/services/report_service.py:98-105**

**Issue:** overdue_count 统计 Repayment.status == "逾期"，但全项目无任何写入路径——repayment_service.confirm_repayment（repayment.py:15-26）只做 待还 -> 已还，无"逾期"迁移。overdue_count 恒为 0，对比表"逾期笔数"永远是 0。

**同源不一致:** 预警 REPAYMENT_OVERDUE（alert_service.py:35-39）用的是 status=="待还" AND due_date < today，与对比表的 status=="逾期" 口径不一致。

**Fix:** 将 overdue_count 改为与预警一致的口径：Repayment.status == "待还" AND Repayment.due_date < today。另注意 CapitalAllocation.status="逾期" 同样无写入路径（capital_service.py:74,275 引用但无人置值），为死分支，不影响在途调配求和，可清理。

---

## 2. MEDIUM 发现

### M1. 验收驳回（reject_acceptance）无审计日志
**File: backend/app/services/acceptance_service.py:76-83；端点 backend/app/api/v1/endpoints/acceptances.py:49-56**

**Issue:** P1 计划 §2.2 明确 ACCEPT_APPROVE 覆盖"验收通过/驳回"；approve_acceptance 写审计（acceptance_service.py:67-70），但 reject_acceptance 仅改状态、无 audit.log。驳回是敏感审批动作，应留痕。
**Fix:** 在 reject_acceptance 内 db.flush() 后补 audit.log(action="ACCEPT_APPROVE", after_json={"status":"已驳回"}).

### M2. 分项目 Tab 缺"闲置/缺口"标识（spec deviation）
**File: frontend/src/views/CapitalView.vue:148-158**

**Issue:** P1 计划 §3.2 要求"表格 + 闲置/缺口标识（净头寸>阈值标'可调出'、<0 标'缺口'）"。现状仅渲染 6 个数值列，净头寸为负（缺口）的项目 allocatable 显示 0.00，无红色缺口标识、无"可调出"标签，"哪个项目缺钱"无法一屏识别。
**Fix:** 对 net_position < 0 行加红色缺口 NTag，对 allocatable > 0 加"可调出"标签。

### M3. 预警 DISBURSE_DELAY 永不触发（planned_date 无写入路径）
**File: backend/app/services/alert_service.py:60-67**

**Issue:** 规则筛选 LeasingNode.planned_date IS NOT NULL，但全项目仅 schemas/leasing.py:41 声明字段、无任何 service/endpoint 写入 planned_date（create_process leasing_service.py:52-54 建节点时不设；advance_node 只写 actual_date）。节点计划日恒为 NULL，规则永久静默。
**Fix:** 创建金租流程时按模板/默认写入 planned_date，或在 advance_node/前端放款节点可编辑计划日后再启用该规则。

### M4. 预警 DELIVERY_STUCK 只覆盖"进行中"，漏"未开始"阶段（"stuck 或未动"未全实现）
**File: backend/app/services/alert_service.py:77-85**

**Issue:** 计划要求"交付阶段卡住（stuck 或未动）>7 天"。现仅 status=="进行中" AND updated_at < today-7d；一个 7+ 天从未推进的"未开始"阶段（未动）不报警。若业务流程停在第 N 阶段从未置"进行中"，无法预警。
**Fix:** 将"未开始"但 updated_at 距今 >7 天的阶段（排除首阶段/新创建当天）纳入，或扩展触发条件。
---

## 3. LOW 发现

### L1. 审计日志写入时序均在 after_action 之前（功能等价，非 bug）
**File:** capital_service.py:167-174、leasing_service.py:146-150、order_service.py:101-106、invoice_service.py:178-185、acceptance_service.py:66-72、confirmation_service.py:62-70

**Issue:** 题目假设"after_action 之后写审计"；实际所有 service 均为 业务 flush -> audit.log -> after_action。因 audit.log 只 db.add 不 flush、after_action 内部异常被 try/except 吞掉、二者同事务由 endpoint 统一 commit，先后顺序不产生任何状态差异（无孤儿审计、无半提交）。故判定 PASS，仅记录观察。
**补充确认:** SUPERSEDE 审计在 disburse 主 flush 之前（leasing_service.py:126-127）写入，但 execute_replacement 已内部 flush 物化 fr.id（funding_service.py:82），无时序问题。

### L2. "逾期"状态（Repayment / CapitalAllocation）无写入路径
**File:** backend/app/services/repayment_service.py:15-26、backend/app/services/capital_service.py:74,275

死分支。capital_allocations.status="逾期"、repayments.status="逾期" 均无人置值，仅被 in_transit 求和、return_allocation 允许状态、对比表/预警引用。对在途调配求和与归还判定无影响，但状态机语义空洞，建议同步 H3 清理。

### L3. portfolio 停滞天数边界
**File:** backend/app/services/workflow_service.py:319

(datetime.utcnow() - updated_at.replace(tzinfo=None)).days：UTC 口径正确；已完成项目停滞天数持续增长（可接受）；.days 截断小数（6 天 23 小时显示 6 天）。建议对"已完成"项目显示"—"。

### L4. 缺 pool-by-project / portfolio / project-comparison 的边界用例测试
**File:** backend/app/tests/test_query_endpoints.py:31-90

现有测试仅覆盖 happy path：pool-by-project 无置换场景（未覆盖 H1）；project-comparison 无已付款应付发票场景（未覆盖 H2）、无逾期还款（未覆盖 H3）。建议补：含置换的池余额断言、含采购已付款发票的回款率断言、due_date < today 待还还款的 overdue_count 断言。

---

## 4. 安全审计（范围内确认项）

| 项 | 结论 | 位置 |
|---|---|---|
| 硬编码密钥 | PASS — seed 密码已改 env（S1 修复） | seed.py:13 os.getenv("SEED_PASSWORD","sie123") |
| SQL 注入 | PASS — 全 ORM 参数化，无字符串拼接 | capital/reports/workflows/alert_service 全部 |
| 审计 action CHECK 双同步 | PASS — alembic 0004 与 schema.sql 均含 DISBURSE/CAPITAL_TXN/LIGHT_ON/ALLOCATE/ALLOCATE_RETURN 等 | 0004_audit_log_write.py:17、schema.sql:494 |
| CORS / 错误泄漏 | PASS — 白名单收敛、IntegrityError 统一 409 不回 SQL | main.py:14-21, 24-30 |
| 敏感操作鉴权 | 已决策暂缓（非回归） — 红冲/调配/放款/核销端点仅校验登录，无角色管控；计划 §0 决策 #1 明确暂缓，审计留痕已先行覆盖 | capital.py:83-95、leasing.py:68-85、acceptances.py:39-46 |

---

## 5. 逐项核对（7 项审计重点）

| # | 审计点 | 结论 | 证据 |
|---|---|---|---|
| 1 | 审计日志写入时机（after_action 之后、业务 flush 之后） | PASS — 全部在业务 flush 后、同事务提交；相对 after_action 的顺序功能等价（见 L1） | 各 service 见 L1 |
| 2 | pool-by-project 净头寸/可调余额/在途调配 | FAIL — 净头寸/可调余额被置换归还双计虚增（H1）；在途调配(借出未还)与可调余额口径一致正确 | capital_service.py:61-97、funding_service.py:51-63 |
| 3 | portfolio 停滞天数 | PASS — UTC 口径正确，语义=自上次工作流推进 | workflow_service.py:319 |
| 4 | project-comparison 回款率/IRR | FAIL — IRR/NPV/总利润提取正确（irr_annual_pct key 匹配 profit_service.py:149）；回款率含应付发票（H2）；逾期笔数恒 0（H3） | report_service.py:86-105 |
| 5 | 4 条预警规则（还款逾期/交付卡住/合同到期/工作流停滞） | WARNING — 还款逾期、合同到期、工作流停滞三条匹配；交付卡住只覆盖"进行中"漏"未开始"（M4） | alert_service.py:35-39,77-85,87-96,98-109 |
| 6 | 分项目 Tab 前后端对应 | PASS — 6 列 key（project_name/net_position/allocatable/in_transit/recent_30d_in/out）与后端完全对应，行内"调配"预填 from_project_id 正确；缺闲置/缺口标识（M2） | CapitalView.vue:149-157 对 capital_service.py:91-96 |
| 7 | 组合总览/对比表列定义 vs 后端字段 | PASS — 组合总览 6 列全对应（PortfolioView.vue:34-47 对 workflow_service.py:320-326）；对比表 7 列全对应（ComparisonView.vue:22-50 对 report_service.py:115-122）；Dashboard 卡片字段亦全对应 | Dashboard.vue:134-164 |

---

> 附：本报告发现与既有审计的关系——H1 即 v3.1 审计 A4 的"余额逻辑需确认"（MEDIUM），本次坐实为方向性错误并升级 HIGH；其余为新发现。修复优先级建议：H1 -> H2 -> H3 -> M1 -> M4。
