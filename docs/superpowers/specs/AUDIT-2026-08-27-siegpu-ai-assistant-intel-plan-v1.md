# 审计一：智能层计划书 v1.0 逐行事实核对

> 日期：2026-08-27 | 对象：`2026-08-27-siegpu-ai-assistant-intel-plan.md` v1.0 | 方法：逐断言核验（代码/DB/目录实查）
> 结论：**FAIL 2 / WARN 2 / PASS 14**，已全部修正，计划书升级 v1.1。

## 审计发现

| # | 级别 | 计划书断言 | 核验方法 | 结果 | 处置 |
|---|---|---|---|---|---|
| F1 | 🔴 FAIL | §2.2「接入现有 pytest 全量（CI 已跑 pytest，零额外接线）」 | `Get-ChildItem .github` → 不存在 | **仓库无 CI**，断言为假 | B2 重写为「并入 pytest 全量（部署前容器必跑）」；CI 列入开放问题 #5；§0 基线表补「CI：不存在」行 |
| F2 | 🔴 FAIL | §4.3「record_income → record_transaction(source_type=回款, direction=IN)」 | `schema.sql` capital_transactions CHECK 实查 | 枚举=自有资金/银行流贷/金租融资/**租金收入**/调配/调配归还/还款/归还流贷/归还自有/汇兑损益/预付/归还银行——**无「回款」**，按此写入会 DB 层炸 | 改为 source_type='租金收入'（系统口径：客户回款=租金收入）；§4.2 dry_run 校验清单补「amount>0」（DB CHECK amount>0 硬约束） |
| F3 | 🟡 WARN | §5 M-A=2.5d / M-C=3.5d | WBS 分项加总 | A 实为 2.6d，C 实为 3.4d（总数 7.0 碰巧对） | 里程碑表改为真实加总，括号注明分项 |
| F4 | 🟡 WARN | §2.2「报告落盘 output/assistant_eval/」 | 目录实查 | 后端无 output/ 既有惯例（VERA 的结构，不是本仓库的） | 注明「backend/output/assistant_eval/，目录运行时创建」；补 eval 成本说明（≈≤12万 token/次，手动跑） |
| F5 | ✅ PASS | §0 工具 14 / KB 23 / 金标 24 题 4 层 / 迁移头 0025 | 容器内逐项执行 | 全部一致 | — |
| F6 | ✅ PASS | §0「eval.py 存在但从未真跑」 | 文件存在 + 无 output/assistant_eval 目录 | 一致 | — |
| F7 | ✅ PASS | §0「HISTORY_ROUNDS=6」 | `memory.py` 实查 `HISTORY_ROUNDS = 6` | 一致 | — |
| F8 | ✅ PASS | §0「反馈闭环已上线」 | `/feedback` 端点 + assistant_gaps 表 + 0025 迁移实查 | 一致 | — |
| F9 | ✅ PASS | §0「配额 agent 各轮累计已修复」 | 冒烟实测 196310→181014 | 一致 | — |
| F10 | ✅ PASS | §0「audit CHECK 20 枚举无助手动作」 | pg_constraint 实查 | 一致（20 值，扩枚举迁移模式有 0008/0011 先例） | — |
| F11 | ✅ PASS | §4.3 四个写目标服务签名 | 逐函数实查：record_transaction/generate_billing_device/mark_step_done/allocate(含 idempotency_key) | 一致 | — |
| F12 | ✅ PASS | §4.3「draft_billing 有唯一索引幂等」 | schema `uq_billing_period ON billings(device_id, period_index)` | 一致 | — |
| F13 | ✅ PASS | §4.8「确认后 audit 含 CAPITAL_TXN + ASSISTANT_WRITE」 | record_transaction 源码内建 `_audit.log(action=CAPITAL_TXN)` | 一致（双留痕成立） | — |
| F14 | ✅ PASS | §3.4 注入点 `_system_with_context` 存在 | endpoints/assistant.py 实查 | 一致（注意：现签名无 question 参数，A-4 需扩展——已属 WBS 范围） | — |
| F15 | ✅ PASS | §3.2/3.5 kind 枚举与工具参数自洽 | 计划内部交叉读 | 一致 | — |
| F16 | ✅ PASS | §0「501 passed」 | pytest 全量实跑 | 一致 | — |

## 系统性观察

1. 计划书最大的事实风险集中在「对仓库既有设施的存在性假设」（CI、枚举值、目录惯例）——均属**未实查就引用**。后续计划书模板应加一节「存在性断言清单」，凡引用既有设施必须附验证命令。
2. 枚举类断言（source_type/action CHECK）必须以 schema.sql/DB 实查为准，不能凭业务直觉命名——F2 即此病。

## 修正后状态

计划书已更新为 **v1.1**（F1-F4 全部修正），进入审计二（对抗性设计完备性审查）。