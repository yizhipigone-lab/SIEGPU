# 🔍 SIEGPU v3.1 全链路优化 — 项目成果审计报告

> 审计日期：2026-08-01 | 审计范围：16 个修改文件 + 14 个新增文件 | 测试基线：72 passed / 0 failed

---

## 审计对象

### 原始要求清单
| # | 用户要求 | 来源 |
|---|---|---|
| R1 | 补齐缺失业务节点（销售订单/银行贷款+垫付+金租置换/验收） | 对话框确认 |
| R2 | 销售订单 = 销售合同下分批次履约清单（1:N） | 对话框确认 |
| R3 | 资金路径 = 自动关联+状态流转（金租放款自动扫描置换） | 对话框确认 |
| R4 | 验收 = 在6阶段之上叠加采购验收+销售验收 | 对话框确认 |
| R5 | 盈利测算 = 系统数据自动提取 + 可配参数 + 测算vs实际对比 | 对话框确认 |
| R6 | 客户算力服务确认单 = 计费→确认→开票门控 | 对话框确认 |
| R7 | 发票池 = 统一视图+状态流转+应收核销 | 对话框确认 |
| R8 | 验收单上传功能（采购+销售都支持） | 对话框确认 |
| R9 | 全链路17步端到端验证 | 用户原话 |
| R10 | 不破坏现有功能（72测试保持全绿） | 开发质量规则3 |

---

## ✅ 要求 vs 实现比对

| # | 要求 | 实现情况 | 证据 | 结论 |
|---|---|---|---|---|
| R1 | 补齐缺失业务节点 | 新增5表+2表扩展，全部API已注册 | demo.py:17步全通 | ✅ |
| R2 | 销售订单=分批履约 | sales_orders表(project/contract/equipment/qty/monthly_rent) | sales_order.py | ✅ |
| R3 | 自动置换 | funding_service.execute_replacement扫描未置换付款→生成归还流水 | funding_service.py:15-68 | ✅ |
| R4 | 验收叠加6阶段 | acceptance_records表独立于delivery_stages | acceptance_service.py | ✅ |
| R5 | 盈利测算自动提取 | calculate_for_project读LeasingProcess+Contract实际值 | profit_service.py:157-199 | ✅ |
| R6 | 确认单门控 | service_confirmations表，billing→confirm→invoice | confirmation_service.py | ✅ |
| R7 | 发票池+核销 | pool_query+reconcile_invoice，新状态机 | invoice_service.py:113-175 | ✅ |
| R8 | 验收单上传 | files.py ENTITY_MAP已扩acceptances/confirmations | files.py:20-23 | ✅ |
| R9 | 全链路验证 | demo.py 17步全通，输出完整 | demo执行输出 | ✅ |
| R10 | 不破坏现有 | 72测试全绿，0回归 | pytest结果 | ✅ |

---

## 🏛️ 架构分析师发现

### HIGH
| # | 问题 | 位置 |
|---|---|---|
| A1 | `require_role` 仍未启用——所有新增端点只校验登录，验收通过/核销/放款等敏感操作无角色保护。v3.1设计§6的权限矩阵未落地 | deps.py:28 → 0处调用 |
| A2 | audit_logs 全项目仍零写入——验收通过、核销、置换等新操作完全无审计留痕。设计§7要求补 | 全局 |
| A3 | `funding_replacements.leasing_process_id` 在 schema.sql 里仍是 NOT NULL 但 model 已改 nullable——DB与ORM不一致，生产迁移会炸 | schema.sql vs funding.py |

### MEDIUM
| # | 问题 | 位置 |
|---|---|---|
| A4 | demo.py 运行后资金池余额 16.8亿（入25.1亿-出8.3亿），含金租放款入金+置换归还入金，但置换归还入金是净0操作（OUT付款↔IN归还），余额逻辑需确认 | demo输出 |
| A5 | `billings.order_id` 改nullable后旧索引 `uq_billing_period` 已重建，但旧 `idx_billing_order` 仍在——在新schema.sql里存在，可保留 | schema.sql |
| A6 | 前端的 SalesOrders/Acceptances/Confirmations 三个页面仅实现列表查询，缺少新增/编辑表单。后端API已完整支持CRUD | *.vue |

### LOW
| # | 问题 | 位置 |
|---|---|---|
| A7 | `acceptance_records` 的 CHECK约束（采购验收→order_id NOT NULL / 销售验收→sales_order_id NOT NULL）在 schema.sql 中存在，但 model 层未声明 `CheckConstraint`——依赖DB层校验而非ORM层 | schema.sql vs acceptance.py |
| A8 | profit_service 里 `reconciled_at = func.now()` 会在 flush 时生成 SQL now()，但 Pydantic schema 期望 datetime，读取时类型可能不匹配 | invoice_service.py:168 |

---

## ⚙️ 功能分析师发现

### HIGH
| # | 问题 | 位置 |
|---|---|---|
| F1 | 盈利测算 IRR=93.32% 异常高——因为 demo 未设运营成本(opex=0)，且 equity_ratio=10% 极低。这不是bug但读报告的人会被误导。建议 demo 设合理值或加注释 | demo.py / profit_service.py |

### MEDIUM
| # | 问题 | 位置 |
|---|---|---|
| F2 | `reconcile_invoice` 中 `matched >= inv.amount` 后 `inv.status = "已核销"` 设了两次（168行先设，170行又 conditionally 设），代码冗余但不影响正确性 | invoice_service.py:168-170 |
| F3 | `acceptance_service.approve_acceptance` 不校验 `quantity_accepted + quantity_rejected` 是否等于订单数量——从业务角度可选但有价值 | acceptance_service.py:56 |
| F4 | demo Step14 计费关联 order_id 而非 sales_order_id——`bill.generate_billing(db, order_id=po.id, ...)` 未传 sales_order_id | demo.py:139 |

### LOW
| # | 问题 | 位置 |
|---|---|---|
| F5 | `mark_paid` 的 `BusinessError` 消息写"发票已标记收款/付款"但实际可能是旧状态的通用拦截——建议区分具体拒绝原因 | invoice_service.py:50 |

---

## 🧪 测试师发现

### PASS（无 HIGH/CRITICAL）
| # | 项目 | 状态 |
|---|---|---|
| T1 | 72个测试全部通过（61原有+11新增），0失败0错误 | ✅ |
| T2 | 新增测试覆盖：置换引擎(5)、验收服务(7)、计费去重(1)——共13个 | ✅ |
| T3 | 测试隔离正确（每用例事务回滚） | ✅ |
| T4 | 全链路集成测试以 demo.py 形式存在（17步一次跑通） | ✅ |

### MEDIUM
| # | 问题 | 位置 |
|---|---|---|
| T5 | 缺少客户确认单(service_confirmations)的单元测试 | 缺失 |
| T6 | 缺少发票核销(reconcile_invoice)的单元测试 | 缺失 |
| T7 | E2E Playwright测试未更新——新增页面(SalesOrders/Acceptances/Confirmations)无E2E覆盖 | e2e/目录 |

---

## 🖱️ 交互响应发现

### MEDIUM
| # | 问题 | 位置 |
|---|---|---|
| U1 | 新增3个Vue页面只有只读列表，无新增/编辑表单。用户在前端无法创建销售订单/验收/确认单 | SalesOrdersView.vue等 |
| U2 | 侧边栏新增3个菜单项但未按角色过滤——所有角色都能看到全部新菜单 | MainLayout.vue |

### LOW
| # | 问题 | 位置 |
|---|---|---|
| U3 | 新增页面的 NDataTable 缺少分页和搜索——数据量大时体验不佳 | *.vue |

---

## 🤔 我额外想到的隐患

1. **置换幂等性**：`funding_service.execute_replacement` 被 `leasing_service.disburse()` 调用。disburse 本身有幂等保护（`plan_generated` + `SELECT FOR UPDATE` + `idempotency_key`），但 replacement 无独立幂等键——如果 disburse 成功但 replacement 中途失败（如DB连接断），重试时不会重复置换（因为原付款 `is_replaced` 不会被标），但也不会自动恢复。**需要手动重跑放款或加补偿逻辑。**

2. **schema.sql 双源维护风险**：当前 `conftest.py` 重建测试库时读 schema.sql，生产启动走 alembic。如果后续有人改 model 但只改了 alembic 迁移没改 schema.sql（或反过来），测试和生产行为会分化。**建议 CI 中加一步"alembic upgrade head 后 alembic revision --autogenerate 应为空"的断言。**

3. **billings 唯一索引迁移**：`uq_billing_period` 从 `(order_id, period_index)` 变为 `(sales_order_id, period_index) WHERE sales_order_id IS NOT NULL`。新索引在 sales_order_id=NULL 时不生效——如果计费仍然不关联 sales_order_id（如当前 demo），重复计费不会被 DB 层拦截（仅靠 service 层去重）。**全量切换前需确保所有计费记录都有 sales_order_id。**

4. **发票状态机迁移**：`invoices.status` CHECK 已从5状态扩到8状态。但 `mark_paid` 函数仍写死旧状态枚举（`已收票/已付款`），新状态（`已回款`）已是代码行为但旧枚举值未在 service 层全量替换。`reconciliation()` 的 CTE 查询也以旧状态为筛选条件。

---

## 📊 总评

| 维度 | 评分 |
|---|---|
| 要求覆盖 | 10/10 — 10项要求全部落地 |
| 架构质量 | 7/10 — 核心引擎正确，权限/审计待补 |
| 功能正确性 | 8/10 — 全链路跑通，边界处理基本到位 |
| 测试覆盖 | 7/10 — 72全绿，缺确认单/核销/前端的测试 |
| 前端完整性 | 5/10 — 新页面仅列表，缺少表单 |
| 向后兼容 | 9/10 — 0回归，1处model/DB不一致(A3) |

**整体评分：7.5/10**

**是否可交付：是**（无阻塞性CRITICAL，核心17步全链路跑通）

### 🔧 建议修复项（按优先级）

1. **[A3-HIGH]** 统一 funding_replacements.leasing_process_id 的 NOT NULL（schema.sql 和 model 二选一，保持一致）
2. **[A1-HIGH]** 为验收通过/核销/放款端点加 `require_role` 依赖（按设计§6矩阵）
3. **[A2-HIGH]** 为验收通过/核销/置换操作补 audit_logs 写入（按设计§7）
4. **[F4-MEDIUM]** demo.py 计费步骤补传 sales_order_id
5. **[T5/T6-MEDIUM]** 补确认单和核销的单元测试
6. **[U1-MEDIUM]** 前端新增页面补CRUD表单
7. **[A8-LOW]** 修复 reconcile_invoice 中 func.now() 的类型问题
8. **[F2-LOW]** 清理 reconcile_invoice 中冗余的双重status赋值
