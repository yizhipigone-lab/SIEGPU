# AUDIT-ARCH-2026-08-01 — SIEGPU 审计留痕 + 多项目管理 架构审计

> 审计对象：36 变更文件（P0 审计留痕 C4 + P1 多项目并行）| 日期：2026-08-01
> 结论：5 项检查 → 1 CRITICAL（已修复）/ 4 WARNING / 4 PASS

---

## 检查 1 — audit_service 埋点覆盖完整性

### 结论：PASS（2 WARNING）

已覆盖 11 处（10 类 action + 驳回），均为 `db.flush()` 后同事务原子写入：

| 触发点 | action | 位置 |
|---|---|---|
| record_transaction | CAPITAL_TXN | capital_service.py:169 |
| allocate | ALLOCATE | capital_service.py:225 |
| reverse_transaction | REVERSE | capital_service.py:265 |
| return_allocation | ALLOCATE_RETURN | capital_service.py:294 |
| disburse | DISBURSE | leasing_service.py:147 |
| execute_replacement | SUPERSEDE | leasing_service.py:126 |
| reverse_invoice | REVERSE | invoice_service.py:112 |
| reconcile_invoice | RECONCILE | invoice_service.py:180 |
| confirm | CONFIRM_UPLOAD | confirmation_service.py:64 |
| approve_acceptance | ACCEPT_APPROVE | acceptance_service.py:68 |
| reject_acceptance | ACCEPT_APPROVE（驳回） | acceptance_service.py:82 |

**WARNING**：`confirm_repayment`/`mark_paid`/`generate_billing` 为资金敏感操作但未埋点（不在计划 §2.2 显式 action 表内，属合理补强范围）。`at=datetime.utcnow()` 为 naive UTC，建议让 server_default 生效。

---

## 检查 2 — 分层正确性

### 结论：PASS

- 全部 endpoint 从 `get_current_user` 取 `user.id` 透传给 service 作为 actor
- `/portfolio` 路由遮蔽（CRITICAL）已修复：移到 `/{project_id}` 之前
- 路由注册齐全

---

## 检查 3 — 循环依赖

### 结论：PASS

全部 service 间交叉引用用函数内延迟 import，无模块级循环依赖。

**WARNING**：`capital_service.pool_by_project` 每项目 ~5 次查询，N+1；`models/billing.py:69-77` 后挂 column_property 对 Invoice 全表查询每行带 correlated subquery。

---

## 检查 4 — SQL 注入

### 结论：PASS

- completion_check 动态表名过白名单 `ALLOWED_TABLES` frozenset
- 全部查询走 ORM 绑定参数，无字符串拼接
- `PATCH /steps/{seq}` 挂 `require_role("ADMIN")`

---

## 检查 5 — 迁移链

### 结论：PASS

0001→0002→0003→0004 线性正确，全部含 downgrade。CHECK 双同步（schema.sql + Alembic 同值）。
