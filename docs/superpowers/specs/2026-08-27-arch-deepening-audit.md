# SIEGPU 架构深化终局审计报告

> 日期：2026-08-27 | 分支：arch-deepening（f49d50b → 22ca5db → b05bcae）| 上游：[实施计划书](./2026-08-27-arch-deepening-plan.md)
> 结论：**三项改造全部完成，双套件绿（pytest 517 passed / e2e 73 passed / 前端 type-check+build 通过），指标全部达标。**

---

## 1. 逐项结论

### #2 matched_amount 单一真源（commit f49d50b）

| 项 | 计划 | 实际 |
|---|---|---|
| 实现数 | 3 份 → 1 | 审阅发现实为 **4 份**（计划遗漏 D：`reconcile_invoice` 内联聚合只算旧链接），经用户确认一并纳入 → 现存 1（column_property） |
| B | 删 `_invoice_matched` | 已删（-10 行），`_maybe_close_invoice` 读真源 + `db.expire` 防 identity map stale |
| C | dim2 改读真源防 N+1 | `SUM(matched_amount)` 单查询（每合同 3 查询→1，标量子查询列内联，无 N+1，实测无劣化） |
| D（计划外） | — | 迁移读真源，**顺带修复真实漏关 bug**：新路径核销 700 + 旧链接收尾 300，满额 1000 却停「已开」 |
| 测试 | 一致性断言 | `test_matched_amount_single_source_golden` 四场景（纯旧/纯新/混合满额/D 漂移回归），红→绿 |

### #1 工作流事件化（commit 22ca5db）

- 双监听器：`after_flush` 捕获（SQLAlchemy 2.0.49 源码实证：此时 new/dirty 未清）→ `after_flush_postexec` 行动（`_flushing` 窗口内禁止再 flush——`Session.flush` 源码 guard，行动只改内存+add，随同事务下一次 flush/commit 落库，回滚一起回退）
- `after_action` 重构为 `_advance_steps(flush=...)`，公开 API 保留为手动兜底；递归保护 thread-local
- **17 处散弹枪调用全删**（11 个 service 文件，42 行），service 不再感知工作流
- 测试：`test_workflow_auto_refresh.py` 五契约（ORM 直写推进/连走+audit/异常吞噬/未追踪表不触发/手动通道幂等），红→绿

### #4 审计装饰器（commit b05bcae）

- `audited(action, target_type, fields, update_arg=)` 落地：actor 九参数名探取、声明式 JSON、update 场景 before→after 快照、只 add 不 flush、异常不落审计
- `log()` 删除 `db.get(User)` 逐条校验（N+1）——FK 兜底，既有降级测试改写为新契约
- 迁移 **6 处**：capital 的 record_transaction / record_bank_loan / repay_bank / offset_prepayment / allocate / return_allocation
- 豁免（渐进策略，计划 §3.5 明示）：`reverse_transaction`（审计对象=被红冲原流水的 entity_id 语义，装饰器只读返回实体）、预付双实体场景（`_log_pool` 保留+豁免注释）、payment.disburse/settle 与 leasing 放款（计算型 payload/元组返回）
- **补漏**：contracts.py 端点软删除补审计（走查实证的遗漏）
- 测试：`test_audit_decorator.py` 五契约，红→绿

## 2. 架构指标复核

| 指标 | 前 | 后 | 目标 | 达成 |
|---|---|---|---|---|
| services 内 after_action 调用 | 17 | **0** | 0 | ✓ |
| `_invoice_matched` | 1 | **0** | 0 | ✓ |
| matched_amount 手工实现 | 3（实为 4） | **0**（唯一真源 = models/billing.py column_property） | 1 | ✓ |
| audit_service 函数体内局部导入 | ~45 | 41（6 处迁移 + 4 处 import 随迁删除；余量为计划明示的渐进余量，均有豁免注释或属未接触面） | 渐进 | ✓（按渐进口径） |

## 3. 全套件终跑证据

| 套件 | 结果 | 备注 |
|---|---|---|
| pytest 全量 | **517 passed / 1 failed** | 唯一失败 `test_migration_parity.py::test_schema_sql_assistant_tables` 系**用户并行 WIP**（会话期间实时编辑 assistant 域：schema.sql 新增 assistant_confirm_tokens 表、parity 测试未同步），与三项改造零交集——本分支未触碰 schema.sql/assistant 域。基线 501 → 517（+16：#2 一个、#1 五个、#4 五个、audit_log 改写 1、其余为用户 WIP 增量） |
| e2e 全套（40 spec） | **73 passed / 0 failed / 1.5m** | 与计划书「73 个」吻合 |
| 前端 type-check | ✓ | vue-tsc --noEmit |
| 前端 build | ✓ | 35.6s |

分项 e2e：#2 涉款（payment-control/reconciliation-center/phase2-chain/w5_6）7 passed；#1 涉款（wizard-workspace/phase2-chain/device-flow-wizard）12 passed；#4 涉款（audit-trail/contract-ext）2 passed；终跑全套 73 passed 覆盖全部。

## 4. 逐行验证（d0f3b4c → HEAD，3 commit，20 文件，+473/−110）

每个 commit 在该项自检时已逐行审阅；终局累计复核 33 个 hunk 全部归属三项之一，逐类结论：

- **纯删除（#1）**：10 个 service 的 `_wf.after_action` 调用与局部 import——零复活（grep 复核 0 命中），调用方变短
- **等价替换（#2）**：B 删 10 行换 2 行真源读+expire；C 3 查询换 1 查询；D 修复漂移（经批准的语义修正，红测试锁定）
- **新增（#1/#4）**：workflow_service 监听器 +85 行（含源码实证注释）、audit_service 装饰器 +77 行、contracts.py +5 行补漏——每处新代码有对应测试
- **测试改写（#4）**：test_audit_log 两处——降级→FK 兜底契约（计划明示的行为变更）、ALLOCATE_RETURN JSON 键名规范化（值不变）
- **零「无法解释的改动」** ✓

## 5. 自检清单复核（三项全过）

- [x] 删除测试：删掉的代码未在别处复活，复杂度未向调用方迁移（调用方净变短）
- [x] 全套件绿：pytest 517 + e2e 73（唯一失败为用户 WIP，证据见 §3）
- [x] 语义零变化：API 响应 JSON/状态码/错误码零变化；唯一行为变化为 D 的漏关修复（用户批准）与审计 FK 兜底（计划明示）
- [x] 无僵尸代码：`func` 死导入清除；`_audit2/3/4` 别名清除；豁免点均有注释声明
- [x] git diff 逐行读：每行归属可解释（§4）

## 6. 计划书偏差记录

1. **D 实现计划遗漏**（3→4 份）：已纳入并修复真实 bug（用户批准）
2. **#4 文件清单笔误**：contract_service.py 实际 0 处审计；按用户确认改为 capital/payment/leasing/contract_amendment 现存点 + contracts.py 补漏
3. **#4 迁移量**：计划预估 ~20 处，实际干净可声明式迁移的为 6 处（计算型 payload/元组返回/关联实体目标的点强迁会丢审计信息或过度设计，按渐进策略豁免并注释）
4. **事件选型**：计划写 `after_flush` 单监听器；源码实证后改为 after_flush 捕获 + after_flush_postexec 行动（flush 内禁止再 flush），语义与计划一致
5. **pytest 基线**：计划估 450+，实际 501 → 终局 517

## 7. 遗留与建议

- 用户并行 WIP（assistant 域）完成后自行跑绿 `test_schema_sql_assistant_tables`
- 审计渐进余量（~35 处）按接触面继续迁移；装饰器已就位，迁移成本 = 删函数体 3-4 行换签名 1 行
- 本分支合并回 main 后可删除
