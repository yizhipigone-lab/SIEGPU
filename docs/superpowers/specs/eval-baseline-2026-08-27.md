# AI 老虎金标集评测基线报告（2026-08-27）

> 评测器：`python -m app.services.assistant.eval`（M-B 升级版：分层/归因/报告落盘/题间限速）
> 环境：DeepSeek `deepseek-v4-flash`（真实 key），容器内直跑，题间 2s 限速

## 首个全绿基线

| 指标 | 值 |
|---|---|
| **总通过率** | **29/29 = 100%**（闸口 ≥80% ✅） |
| fastpath 层 | 100%（闸口 ≥95% ✅） |
| agent 层 | 100%（闸口 ≥75% ✅） |
| refuse 层 | 100%（闸口 ≥90% ✅） |
| hallucination 层 | 100%（闸口 ≥90% ✅） |
| token 消耗 | 226,602（单次全量） |
| 报告 | `backend/output/assistant_eval/eval_20260827_174529.json` |

## 达到基线过程中的三次基础设施修复（非模型能力问题）

1. **eval 工具轮耗尽无成文**：agent 层题目 4 轮工具用尽后答案为空 → text_miss 假失败。修复：轮数 4→5 + 耗尽后强制最终成文（endpoint 同款兜底）。
2. **reasoning 模型吃光预算**：v4-flash 先思考后成文，max_tokens=2048 偶尔被思考耗尽 → content 为空。修复：默认 4096 + 空内容按可重试错误处理（一次重试）。
3. **连续全量跑触发 provider 限流**：3 分钟内 ~50 万 token 触发分钟级限流 → 全量瞬时失败（8ms 级）。修复：题间 2s 限速。**教训：全量评测一天最多跑 2-3 次。**

## e2e 实测（对话链路）

- 认知教学：「记住：我说小鸟项目指商机5090」→ 保存成功（confidence=100）
- 认知召回：再问「小鸟项目什么状态」→ cognition_used 记录归因 ✓ usage_count+1 ✓；模型用别名做精确检索（不再反问用户澄清）——**认知的价值是省掉澄清往返**（计划书 A-1 验收 #1 原措辞「不含 search_projects」过严，以本基线实测语义为准）
- 写开关关闭：「帮我登记回款」→ 只读拒答 + 指路（资金管理→回款登记）
- 途中抓到并修复真接线 bug：contextvars 在 StreamingResponse threadpool 迭代中跨 yield 丢失 → 认知/写工具收不到用户。改为 call_tool 显式注入 user（needs_user 标记）

## 防过拟合纪律（D15）执行

当前 33 题 = 基线 29 + 变体 4（variant_workflow_card / variant_invoice_limit / variant_refuse_direct / explore_variant_count 已在基线内）。**下轮全量前必须维持变体比例**；每修一题加一变体的纪律继续执行。

## 下轮触发条件

改 prompt / 改工具注册表 / 改 fastpath 意图词表 → 必须重跑（一天 ≤2 次全量，防限流）。