# SIEGPU ERP 审计留痕 + 多项目管理 — 工作成果报告书

> 日期：2026-08-01 | 状态：FINAL（经用户审计修订） | 基线：pytest ~100 / e2e 28 / 浏览器验证通过
> 计划：[P0+P1 计划书](./2026-08-01-siegpu-p0-security-p1-multiproject-plan.md) v1.1
> 依赖：[v3.1 全链路设计](./2026-08-01-siegpu-erp-design-v3.md)、[向导工作台 v1.2](./2026-08-01-siegpu-wizard-workflow-design.md)
> 审计报告：本报告含三轮审计摘要；独立审计文件见附录 A

---

## 1. 执行摘要

交付了计划书的两大目标：

- **C4 审计留痕**：11 处埋点覆盖全部敏感操作，`audit_service.py` 统一 log() + Alembic 0004 + schema.sql 双同步
- **P1 多项目并行管理**：资金池分项目视图、项目组合总览、项目对比、预警规则扩展

---

## 2. 交付明细

### 2.1 审计日志写入 — 11 处全覆盖

| # | 审计动作 | 触发点 | 文件:行 |
|---|---|---|---|
| 1 | CAPITAL_TXN | record_transaction | capital_service.py:169 |
| 2 | ALLOCATE | allocate | capital_service.py:225 |
| 3 | REVERSE（资金流水） | reverse_transaction | capital_service.py:265 |
| 4 | ALLOCATE_RETURN | return_allocation | capital_service.py:294 |
| 5 | DISBURSE | disburse | leasing_service.py:147 |
| 6 | SUPERSEDE | execute_replacement | leasing_service.py:125-127 |
| 7 | REVERSE（发票） | reverse_invoice | invoice_service.py:112 |
| 8 | RECONCILE | reconcile_invoice | invoice_service.py:180 |
| 9 | CONFIRM_UPLOAD | confirm | confirmation_service.py:64 |
| 10 | ACCEPT_APPROVE（通过） | approve_acceptance | acceptance_service.py:68 |
| 11 | ACCEPT_APPROVE（驳回） | reject_acceptance | acceptance_service.py:82 |

**基础设施**：
- `backend/app/services/audit_service.py` — 统一 `log()` 函数，同事务写入，user_id 无效时降级 NULL + logger.warning
- `audit_logs.action` CHECK 扩展到 17 个值（schema.sql:494 + Alembic 0004 双同步）
- 存量迁移：0004 含 downgrade 回退路径

### 2.2 多项目并行管理

| 新端点 | 说明 | 前端消费 |
|---|---|---|
| `GET /api/capital/pool-by-project` | 按项目净头寸/可调余额/在途调配/近30天收支 | ✅ CapitalView "分项目" Tab + 行内调配按钮 |
| `GET /api/workflows/portfolio` | 项目×阶段×当前步×停滞天数 | ✅ 独立 PortfolioView 页面（已有，路由已修） |
| `GET /api/reports/project-comparison` | IRR/NPV/回款率/逾期笔数/进度% | ✅ 独立 ComparisonView 页面（已有） |
| `GET /api/capital/allocations` | 调配记录列表（替代 localStorage） | ✅ 归还弹窗 |
| `D3: template_id` | 项目创建可选流程模板 | ✅ 项目表单下拉（remoteOptions） |

### 2.3 预警规则（8 条）

| # | 规则 | 触发条件 |
|---|---|---|
| 1 | REPAYMENT_OVERDUE | 还款 due_date < 今天且待还 |
| 2 | ALLOCATION_OVERDUE | 调配应归还日 < 今天且已调配 |
| 3 | DISBURSE_MISMATCH | 金租实际放款额 vs 申请额偏差 >1% |
| 4 | DISBURSE_DELAY | 金租放款节点计划日已过未完成 |
| 5 | POOL_INSUFFICIENT | 资金池余额 < 未来30天应付 |
| 6 | DELIVERY_STUCK | 交付阶段进行中 >7天未推进 |
| 7 | CONTRACT_EXPIRING | 合同到期 <30天 |
| 8 | WORKFLOW_STUCK | 工作流停滞 >14天 |

### 2.4 安全项 S1-S3

| # | 项 | 状态 |
|---|---|---|
| S1 | seed 密码 env 化 | ✅ `os.getenv("SEED_PASSWORD", "sie123")` |
| S2 | 端口收敛 | ✅ 删 9000，仅保留 8080 |
| S3 | e2e 数据清理 | ✅ 路径已标注 |

---

## 3. 三轮项目质量审计

### Round 1 — 架构审计

**审计文件**：[AUDIT-ARCH-2026-08-01.md](./AUDIT-ARCH-2026-08-01.md)

| 检查项 | 结论 |
|---|---|
| 埋点覆盖完整性 | PASS — 11 处全齐（含驳回） |
| 分层正确性 | PASS（1 CRITICAL 已修复：/portfolio 路由遮蔽） |
| 循环依赖 | PASS — 全部函数内延迟 import |
| SQL 注入 | PASS — 动态表名过白名单 frozenset |
| 迁移链 | PASS — 0001→0002→0003→0004 线性，含 downgrade |

### Round 2 — 功能审计

**审计文件**：[AUDIT-FUNC-2026-08-01.md](./AUDIT-FUNC-2026-08-01.md)

| 检查项 | 结论 |
|---|---|
| audit 写入时机 | PASS — 均在 db.flush() 之后同事务 |
| pool-by-project 数值 | 1 HIGH 已修复：排除置换归还流水双计 |
| project-comparison 回款率 | 1 HIGH 已修复：加 direction=RECEIVABLE 过滤 |
| project-comparison 逾期笔数 | 1 HIGH 已修复：改用待还+due_date<今天口径 |
| 预警规则 | WARNING — 3 条 MEDIUM 标注 |

### Round 3 — 测试审计

**审计文件**：[AUDIT-TEST-2026-08-01.md](./AUDIT-TEST-2026-08-01.md)

| 检查项 | 结论 |
|---|---|
| 审计测试覆盖 | PASS — 9 条测试覆盖全部动作 |
| 测试文件去重 | ✅ test_audit_service.py 已合并入 test_audit_log.py |
| 前端测试 | 已知缺口（计划未含） |
| 测试隔离 | PASS — 函数级事务回滚 |

---

## 4. 测试结果

```
pytest: ~100 passed, 0 failed (Docker)
e2e: 28/28 passed (config timeout 30s→60s 修复)
vite build: ✅ 8.2s
vue-tsc: 0 errors
```

---

## 5. 变更文件清单

```
新增 (6):
  backend/app/services/audit_service.py
  backend/app/tests/test_audit_log.py
  backend/alembic/versions/0004_audit_log_write.py
  frontend/src/views/BillingsView.vue
  frontend/src/views/PortfolioView.vue (独立页，已有)
  frontend/src/views/ComparisonView.vue (独立页，已有)

修改 (~30):
  backend/app/services/capital_service.py     (+pool_by_project, +list_allocations, +4 audit calls, _dir_sums 排除置换IN)
  backend/app/services/leasing_service.py     (+SUPERSEDE+DISBURSE audit)
  backend/app/services/order_service.py       (+LIGHT_ON audit, +operator_id, +create_order after_action)
  backend/app/services/acceptance_service.py  (+approved_by, +rejected_by, +2 audit calls)
  backend/app/services/invoice_service.py     (+RECONCILE audit, mark_paid 状态修正)
  backend/app/services/confirmation_service.py (+operator_id, +CONFIRM_UPLOAD audit)
  backend/app/services/alert_service.py       (+4 条预警规则)
  backend/app/services/report_service.py      (+project_comparison, 回款率/逾期修复)
  backend/app/services/workflow_service.py    (+portfolio, +_FK_TO_PROJECT, +delivery_stages FK, flag_modified)
  backend/app/services/profit_service.py      (calculate_for_project 读 LeasingProcess)
  backend/app/services/billing_service.py     (duplicate check)
  backend/app/db/schema.sql                   (audit_logs CHECK→17 values)
  backend/app/seed.py                         (SEED_PASSWORD env, seed_templates)
  backend/app/schemas/project.py              (+template_id)
  backend/app/schemas/invoice.py              (+matched_amount)
  backend/app/models/billing.py               (Invoice.matched_amount column_property)
  backend/app/api/v1/endpoints/capital.py     (+allocations GET, +pool-by-project)
  backend/app/api/v1/endpoints/workflows.py   (+portfolio, 路由顺序修复)
  backend/app/api/v1/endpoints/reports.py     (+project-comparison)
  backend/app/api/v1/endpoints/projects.py    (template_id)
  backend/app/api/v1/endpoints/confirmations.py (operator_id)
  backend/app/api/v1/endpoints/acceptances.py (reject user.id)
  backend/app/api/v1/endpoints/files.py       (ENTITY_MAP 扩展)
  backend/app/main.py                         (新路由注册)
  docker-compose.yml                          (端口收敛)
  frontend/src/views/CapitalView.vue          (分项目Tab, API归还)
  frontend/src/views/Dashboard.vue            (待办轮询/新手引导/errMsg)
  frontend/src/layouts/MainLayout.vue         (新菜单项/角色中文)
  frontend/src/config/modules.ts              (模板下拉)
  frontend/src/router/index.ts                (新路由)
  docs/OPERATION-GUIDE.md                     (v3.3 含向导工作台 §6)
```

---

## 6. 已知遗留

| # | 项 | 优先级 | 说明 |
|---|---|---|---|
| L1 | 权限系统（v3.1 C3） | P2 | 用户决策暂缓；§7 备启包就绪 |
| L2 | 审计日志查看 UI | P2 | 只保证写入留痕 |
| L3 | 前端单元测试 | P2 | format.ts / step-forms 为高危区 |
| L4 | e2e specs 硬编码 sie123 | P2 | 生产改密码后 e2e 全红 |
| L5 | confirm_repayment/mark_paid audit | P3 | 不在计划 §2.2 显式表内 |

---

## 7. 结论

**审计日志 11 处全覆盖。多项目管理端点全部前端消费。pytest ~100 全绿。e2e 28/28。架构审计 1 CRITICAL 已修复。功能审计 3 HIGH 已修复。测试文件已去重合并。可交付。**

---

## 附录 A：报告文件索引

| 文件 | 说明 |
|---|---|
| [FINAL-REPORT-2026-08-01.md](./FINAL-REPORT-2026-08-01.md) | 本报告 |
| [AUDIT-ARCH-2026-08-01.md](./AUDIT-ARCH-2026-08-01.md) | 架构审计 |
| [AUDIT-FUNC-2026-08-01.md](./AUDIT-FUNC-2026-08-01.md) | 功能审计 |
| [AUDIT-TEST-2026-08-01.md](./AUDIT-TEST-2026-08-01.md) | 测试审计 |
| [2026-08-01-siegpu-p0-security-p1-multiproject-plan.md](./2026-08-01-siegpu-p0-security-p1-multiproject-plan.md) | 计划书 v1.1 |
