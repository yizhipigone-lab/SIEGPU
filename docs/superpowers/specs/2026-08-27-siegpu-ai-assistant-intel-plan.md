# SIEGPU AI 老虎 · 智能层优化实施计划书 v1.2

> 日期：2026-08-27 | 状态：**v1.2 已全面实施完成**（两轮审计 + 实施 + 基线 100%，见附录 2 实施记录）
> 上游文档：[总体设计 v1.0](./2026-08-27-siegpu-ai-assistant-design.md) · [P0 计划书](./2026-08-27-siegpu-ai-assistant-p0-plan.md)
> 本计划覆盖优化评估中的「智能层（更大投入）」三项：**长期认知沉淀 / 评测质量闸口 / 写操作确认卡**

---

## 0. 现状基线（2026-08-27 实测）

本节所有数字为容器内实测，审计一将逐项复核：

| 维度 | 现状 | 证据 |
|---|---|---|
| 只读工具 | 14 个（10 专用 + 2 计数 + 2 通用探索） | `tools.TOOL_REGISTRY` |
| 知识库 | 23 条策展条目 | `kb.KB_ENTRIES` |
| 金标集 | 24 题，tier = agent/fastpath/hallucination/refuse | `golden_set.json` |
| alembic head | `0025_assistant_feedback` | `alembic_version` 表 |
| 评测器 | `eval.py` 已存在（run/main），**从未用真实 key 跑过**，未接 CI | 文件 + 无运行记录 |
| 会话记忆 | 最近 6 轮（memory.HISTORY_ROUNDS=6），无长期认知 | `memory.py` |
| 反馈闭环 | 👍/👎 + `assistant_gaps` 缺口表已上线 | 端点 `/feedback` |
| 配额闸门 | 日 20 万 token，agent 各轮累计已修复 | config + endpoint |
| 写操作 | 无（用户此前拍板缓做，本计划重启） | TOOL_REGISTRY 全只读 |
| audit_logs action CHECK | 20 枚举值，无助手动作 | pg_constraint 实查 |
| 后端测试 | 501 passed（容器内 pytest，部署前人工触发） | pytest 全量 |
| CI | **不存在**（无 .github/workflows，构建靠 docker compose 手跑） | 目录实查 |

## 1. 目标与范围

**总目标**：AI 老虎从「能答」升级为「越用越聪明 + 质量有闸 + 能办事」。

**In scope**：
- A. 长期认知沉淀（实体别名/口径偏好，自动+显式捕获，注入有预算）
- B. 评测体系实跑 + CI 质量闸口（改动 prompt/工具后有回归防线）
- C. 写操作确认卡（4 个白名单写动作：预览→确认→执行，flag 分级放开）

**Out of scope**（明确不做）：
- 任意 SQL/自由写（安全红线不变）
- 全局共享认知（M1 只做 per-user；全局认知待多用户真实使用后再议）
- 向量库/RAG 引入（KB 23 条用不上；认知表同样走关键词召回）
- 多轮滚动摘要（6 轮窗口 + 认知注入已够 P1 场景）

**实施顺序（重要）**：**B → A → C**。理由：B 的评测闸口必须先于 A/C 的 prompt 改动存在，否则 A/C 每次迭代都在裸奔；C 风险最高放最后且默认 flag 关闭。

---

## 2. 项目 B：评测体系 + 质量闸口（1 个工作日）

### 2.1 问题陈述

- 金标集 24 题从未用真实 key 跑过——**当前通过率是未知的**，P0 验收的「≥80% 闸口」从未兑现；
- `eval.py` 无分层统计、无失败归因、无报告落盘；
- CI 只有 pytest（纯逻辑层），没有任何针对「意图识别正确性」的确定性回归。

### 2.2 设计

**B1. eval.py 增强**（改 `services/assistant/eval.py`）：
- `--tier fastpath|agent|refuse|hallucination|all` 分层执行；
- 每题记录：passed / 耗时ms / token 消耗 / 失败类别（intent_miss / tool_miss / text_miss / tool_ok_but_text_bad）；
- 报告落盘 `backend/output/assistant_eval/eval_YYYYMMDD_HHMMSS.json`（目录运行时创建；含汇总+明细）；
- 注：eval 直调 engine 不走端点配额；全量 24 题 ≈ ≤12 万 token/次，手动跑、不进部署流程；
- 退出码：闸口 <80% → 1（供 CI 判定）。

**B2. 确定性回归层**（新 `app/tests/test_golden_fastpath.py`，审计一修正：本仓库无 CI）：
- 只测 fastpath tier 的**意图命中**（golden 题 → `fastpath.match()` → 与 expect_tools_any 对齐），不调 LLM、不烧 token、毫秒级；
- **并入 pytest 全量**（部署前容器内必跑，与现有 501 项同一条防线）；是否补最小 GitHub Actions CI 列入开放问题 #5；
- 技术注：count/capital 类意图需 db fixture（conftest 提供 siegpu_test 库），guide 类意图 db=None 即可——只断言意图命中，不断言数据。

**B3. 真跑基线 + 修复循环**：
- 用真实 key 跑全量 24 题，产出基线报告存 `docs/eval-baseline-2026-08-27.md`；
- 失败逐题归因修复（预期：refuse/hallucination 类个别题、agent 类 tool_miss），迭代至 ≥80%；
- 修复过程中发现的通用问题回写金标题（金标集是活文档，不是石碑）；
- 防过拟合纪律（审计二 D15）：每修复一题必须同时新增一道变体题（换个问法/换组数据），修的是能力不是答案。

### 2.3 任务拆解（WBS）

| # | 任务 | 文件 | 量 |
|---|---|---|---|
| B-1 | eval.py 分层/归因/报告落盘 | `services/assistant/eval.py` | 0.3d |
| B-2 | fastpath 确定性 CI 测试 | `app/tests/test_golden_fastpath.py` | 0.2d |
| B-3 | 真跑基线 + 失败修复循环 | 金标集 + prompts | 0.5d |

### 2.4 验收标准

1. `pytest app/tests` 含 fastpath 意图回归，全绿；
2. 真跑报告存在且总通过率 ≥80%，分层通过率：fastpath ≥95%、refuse ≥90%、hallucination ≥90%；
3. 低于闸口时 eval 退出码非 0。

---

## 3. 项目 A：长期认知沉淀（2.6 个工作日，审计一 F3 校正）

### 3.1 问题陈述与证据

- 用户说「七号项目」，agent 每次 都要 search_projects 重新解析；解析对了用户没奖励，错了下次还错；
- 用户口径偏好（如「金额一律报万元」）每次对话从零开始；
- `assistant_gaps` 表已在收「答得差的问题」，但没有机制收「用户教过的知识」。

VERA 同源经验（brain/memory.py）：长期认知只存「认知/口径/脉络」，**绝不存金额数字**（记忆隐私纪律）。

### 3.2 表设计（迁移 0026_assistant_cognition）

```sql
CREATE TABLE assistant_cognition (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('entity_alias','glossary_pref','query_hint')),
    key VARCHAR(200) NOT NULL,          -- 检索键：如「七号项目」「金额单位」
    value TEXT NOT NULL,                -- 值：如「指项目 GZZS07202605 商机5090」「报万元」
    source VARCHAR(8) NOT NULL DEFAULT 'auto' CHECK (source IN ('auto','user')),
    confidence SMALLINT NOT NULL DEFAULT 50,   -- user=100；auto=50，误用衰减
    usage_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    created_at/updated_at/deleted_at ...      -- 仓库通用三件套
);
CREATE UNIQUE INDEX uq_asst_cog_user_key ON assistant_cognition(user_id, kind, key) WHERE deleted_at IS NULL;
CREATE INDEX idx_asst_cog_user ON assistant_cognition(user_id) WHERE deleted_at IS NULL;
```

schema.sql 双写 + parity 断言（仓库铁律）。

### 3.3 捕获机制（三条通道，克制优先）

| 通道 | 触发 | 落库 | 置信度 |
|---|---|---|---|
| **显式教授** | 用户说「记住：我说X指Y」→ LLM 调 `save_cognition` | kind=entity_alias/query_hint | 100 |
| **自动别名** | agent 用 search_projects(name=N) 命中唯一项目，且 N ≠ 项目全名 | kind=entity_alias，key=N | 50 |
| **使用强化** | 注入的别名被用到且该回答未收 👎 | usage_count+1, last_used_at | 不变 |
| **负反馈衰减** | 用到某别名的回答收 👎 | confidence−30；≤0 软删 | 衰减 |

**归因前提（审计二 D16 补）**：agent 分支每轮把实际注入且被用到的认知 id 记入 `assistant_messages.tool_calls` 的 `cognition_used` 字段——没有使用痕迹，👎 衰减无从归因。

自动通道必须同时满足：本轮工具链含 search_projects 且唯一命中 + 回答正常完成。不满足就什么都不做（VERA「宁漏勿错」同款）。

**隐私红线（硬校验，落库前执行）**：`value` 经 `guardrails.extract_numbers()` 检出金额样数字 → 拒绝入库（改走 error 提示用户去掉数字）。认知里不许有账。

### 3.4 注入机制（有预算）

- 注入点：`endpoints/assistant.py::_system_with_context`（agent 分支）；
- 召回：`memory.relevant_cognition(db, user_id, question)` —— key 子串命中问题 + 按 usage_count desc，**top 10 条、总长 ≤1500 字符**；
- 格式（**整体包 <data> 标记 + 明确标注来源**——认知 value 是用户可写文本，按「数据非指令」红线处理，防自有数据注入）：
  ```
  ## 已知用户认知（自动召回，可能过期，仅供辅助）
  - 七号项目 → 商机5090（自动学习，用 3 次）
  - 金额口径 → 一律报万元（用户设置）
  ```
- fastpath 分支不注入（快路径要的是毫秒级，认知召回留给 agent 分支）。

### 3.5 工具与端点

- 工具 3 个（注册进 TOOL_REGISTRY，标注「助手自身数据，非业务数据」）：
  `save_cognition(key, value, kind)` / `list_cognition(query?)` / `forget_cognition(id)`；
- RBAC：任意角色，**只能读写自己的行**（user_id=current 强制过滤）；
- 这些是「助手自留地」写入，不进 L2 确认流，但 save/forget 落 `assistant_messages.tool_calls` 天然留痕。

### 3.6 任务拆解（WBS）

| # | 任务 | 文件 | 量 |
|---|---|---|---|
| A-1 | 模型 + 0026 迁移 + schema.sql + parity | `models/assistant.py`、`alembic/versions/0026_*.py`、`db/schema.sql`、`test_migration_parity.py` | 0.5d |
| A-2 | 召回/强化/衰减 + 隐私红线 | `services/assistant/memory.py`（cognition 区块） | 0.7d |
| A-3 | 3 个认知工具 + prompt 探索策略更新（含铁律3措辞改「业务单据」——认知工具写助手自留地不违铁律，审计二 D5） | `tools.py`、`prompts.py` | 0.5d |
| A-4 | 注入接线（agent 分支） | `endpoints/assistant.py` | 0.2d |
| A-5 | 测试：召回/衰减/红线/越权 | `test_assistant.py` + 新 `test_cognition.py` | 0.6d |
| A-6 | 金标集 +3 题（教授/召回/遗忘） | `golden_set.json` | 0.1d |

### 3.7 验收标准

1. 教授「七号项目=商机5090」后，新提问「七号项目流程」——工具链**跳过 search_projects**（认知注入生效，tools_used 不含它）；
2. 👎 后 confidence 衰减、≤0 自动软删；
3. 含金额的 value 被拒（400/工具错误）；
4. 用户 A 查不到用户 B 的认知（越权测试）；
5. 注入块 ≤1500 字符（超预算截断测试）。

---

## 4. 项目 C：写操作确认卡（3.4 个工作日，审计一 F3 校正）

### 4.1 问题陈述

只读是当前能力天花板。「帮我登记回款 500 万」目前只能拒绝并指路。财务用户的高频诉求恰恰是写。

### 4.2 安全架构（D7 三重闸的落地）

```
用户：「帮七号项目登记回款 500 万」
  → LLM 只能调 dry_run 工具（永远没有直接执行通道）
  → writes.dry_run(): 参数解析 + 业务校验（项目存在/方向合法/池校验/amount>0 硬约束）
      → 生成 confirm_token（含：动作+已解析参数+影响金额+5min 过期+幂等键）
  → SSE 下发 card 事件（前端渲染确认卡：参数表+影响金额+警示）
  → 用户点「确认执行」→ POST /api/assistant/confirm {token_id}
  → execute(): ①token 未用未过期 ②参数与 dry_run 一致（服务端为准）
      ③RBAC 复查（token 签发后角色可能被改）④幂等键防重放
  → 调既有 service 层（业务校验/审计/工作流联动全部继承）
  → ASSISTANT_WRITE 审计 + 结果卡回传
```

**不变量（逐条可测）**：
1. LLM 的任何输出都不能触发写——写只由「用户点击确认」这个 HTTP 事件触发；
2. 确认卡上的金额来自 dry_run 的服务端计算，**不采用 LLM 生成的数字**；
3. 一个 token 只能执行一次（幂等键唯一约束兜底）；
4. 确认时重新校验角色与数据状态（token 5 分钟内世界可能变了）；
5. 每次确认/取消/过期都落 audit_logs；
6. 日确认上限 20 次/用户（口径：当日 used_at 非空的 confirm_tokens 行数；防自动化滥用）；
7. 确认=**原子认领**：`UPDATE ... SET used_at=now() WHERE id=? AND used_at IS NULL AND expires_at>now() RETURNING`，认领失败按已用/过期分别 409/410（防并发双击竞态，审计二 D3）；
8. 每个动作声明允许角色（审计二 D13）：record_income → FINANCE_STAFF/FINANCE_DIRECTOR/ADMIN；dry_run 与 execute 双侧校验。

### 4.3 白名单动作（分级放开，flag 控制）

| 动作 | 后端服务 | 风险级 | 默认 |
|---|---|---|---|
| `record_income` 登记回款 | `capital_service.record_transaction(source_type=租金收入, direction=IN)`（审计一修正：source_type 枚举无「回款」，系统口径客户回款=租金收入） | 低（可红冲） | **唯一默认开** |
| `draft_billing` 计费草稿 | `billing_service.generate_billing_device` | 中（有唯一索引幂等） | 关 |
| `advance_step` 流程推进 | `workflow_service.mark_step_done` | 中（可跳步补救） | 关 |
| `allocate_funds` 资金调配 | `capital_service.allocate`（自带 idempotency_key） | 高（跨项目动钱） | 关 |

配置：`assistant_writes_enabled: bool = false`（总开关，**默认全关**）+ `assistant_write_actions: str = "record_income"`（逗号分隔白名单）。上线顺序：内网试用 record_income 一周 → 无事故再逐个开。

### 4.4 表与迁移（0027_assistant_writes）

```sql
CREATE TABLE assistant_confirm_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    action VARCHAR(32) NOT NULL,             -- record_income/draft_billing/...
    params_json JSONB NOT NULL,              -- dry_run 已解析参数（执行以此为准）
    impact_amount DECIMAL(18,2),             -- 影响金额（服务端算）
    warnings JSONB,                          -- dry_run 提示（如「该合同已红冲」）
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,   -- 单次执行兜底
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    result_json JSONB,                       -- 执行结果回写
    created_at/updated_at/deleted_at ...
);
```

同迁移内：audit_logs action CHECK **扩枚举 +1**（`ASSISTANT_WRITE`，只扩不窄——沿用 0008/0011 模式，downgrade 先 DELETE 新动作行再回缩）。

### 4.5 服务与端点

- `services/assistant/writes.py`：`ACTIONS` 注册表（dry_run/execute/影响计算/警示规则）；
- 工具层：每个动作一个 dry-run 工具（desc 明确「只生成预览，不执行」），execute **不注册为 LLM 工具**——只走确认端点；
- 端点：`POST /api/assistant/confirm {token_id}` + `POST /api/assistant/cancel {token_id}`；
- prompt 铁律更新：写请求 → 必须走 dry-run 工具出预览卡 → 绝不声称已完成 → 等用户确认结果。

### 4.6 前端（AssistantDrawer 扩展）

- SSE `card` 事件 → 确认卡组件：动作名徽章 + 参数表 + 影响金额大字 + 警示区 + [确认执行][取消] 按钮；
- 卡片状态机：pending → confirmed/failed/expired/cancelled（按钮防重、过期倒计时）；
- 关闭写总开关时，dry-run 工具不注册 → LLM 按只读话术拒绝（前端无需感知）。

### 4.7 任务拆解（WBS）

| # | 任务 | 文件 | 量 |
|---|---|---|---|
| C-1 | 模型 + 0027 迁移（含 audit CHECK 扩）+ schema + parity | models/alembic/schema/parity | 0.6d |
| C-2 | writes.py（4 动作 dry_run/execute + 警示规则） | `services/assistant/writes.py` | 1.0d |
| C-3 | dry-run 工具注册 + confirm/cancel 端点 + prompt 铁律 | `tools.py`、`endpoints/assistant.py`、`prompts.py` | 0.6d |
| C-4 | 前端确认卡 + card 事件处理 | `AssistantDrawer.vue` | 0.6d |
| C-5 | 测试：token 生命周期/幂等/RBAC 复查/过期/限额/审计落库 | `test_writes.py` | 0.5d |
| C-6 | 金标集 +3 题（写意图→出卡；确认前不执行；开关关闭→拒） | `golden_set.json` | 0.1d |

### 4.8 验收标准

1. 金标集写意图题：回答包含预览要素（动作+金额），**且全程无业务表写入**（DB 断言）；
2. 确认后业务表恰好新增一行（回款：capital_transactions +1，audit 含 CAPITAL_TXN 与 ASSISTANT_WRITE 两行）；
3. 同 token 二次确认 → 409，业务表不再新增；
4. 过期 token 确认 → 410；非本人 token → 403；
5. 总开关关闭时 dry-run 工具不存在于 openai_tools()（测试断言）；
6. 日确认第 21 次 → 拒绝并提示。

---

## 5. 里程碑与工作量汇总

| 里程碑 | 内容 | 工作日 | 依赖 |
|---|---|---|---|
| M-B | 评测闸口先行 | 1.0 | 无 |
| M-A | 认知沉淀 | 2.6（0.5+0.7+0.5+0.2+0.6+0.1） | M-B（prompt 改动有回归防线） |
| M-C | 写操作确认卡 | 3.4（0.6+1.0+0.6+0.6+0.5+0.1） | M-B；flag 默认关 |
| **合计** | | **7.0** | |

## 6. 风险登记册

| # | 风险 | 概率×影响 | 缓解 |
|---|---|---|---|
| R1 | 认知投毒：错误别名越用越错 | 中×中 | 置信度衰减 + 👎 即衰减 + 用户可 list/forget + 注入块标注「可能过期」 |
| R2 | 评测真跑发现大量题失败 | 中×中 | 这正是 B 先行的价值：基线先行，失败即修复清单 |
| R3 | 写操作财务事故 | 低×高 | 三重闸 + 默认只开 record_income + 日限额 + 可红冲 + 审计双留痕 |
| R4 | prompt 膨胀（认知+实体清单+新铁律） | 中×低 | 认知注入 ≤1500 字符硬预算；B1 的 eval 每题记录 prompt token 消耗，作为膨胀观测点（超基线 +30% 告警） |
| R5 | eval 烧钱失控 | 低×低 | 全量 24 题 ≈ ≤12 万 token/次；CI 只跑零 LLM 的确定性层 |
| R6 | 迁移 0027 audit CHECK 回缩踩历史数据 | 低×中 | downgrade 先 DELETE ASSISTANT_WRITE 行（0008/0011 成熟模式） |
| R7 | 确认卡被并发重放 | 低×高 | idempotency_key UNIQUE + used_at 条件更新（乐观锁语义） |
| R8 | 别名自动捕获误存（如把「那个项目」存成别名） | 中×低 | 唯一命中 + 名称≠全名 + 长度≥2 + 不含代词黑名单 |

## 7. 回滚策略

- 0026/0027 均为**纯加表/加列/扩枚举**，无损可逆（downgrade 全反序 DROP）；
- 写功能：`assistant_writes_enabled=false` 即刻全关（代码不删，只断电）；
- 认知注入：`assistant_cognition_enabled=true`（A-1 落 config）一键关闭，`relevant_cognition` 直接返回空；
- 评测 CI：纯增量，删除测试文件即回滚。

## 8. 开放问题（实施前需拍板）

1. 自动别名捕获是否要「同别名出现 2 次才落库」（更保守）？——建议 M1 先按 1 次落库+50 置信度，看 R8 实际发生率再收紧；
2. `record_income` 的参数面：MVP 只支持「项目+金额+日期+备注」四参数，发票核销联动是否纳入（复杂度翻倍）？——建议不纳入；
3. 日确认限额 20 是否合适？——建议先 20，试用后按 gaps/审计数据调；
4. 全局认知（跨用户共享别名表）：M1 明确不做，何时做看多用户使用情况；
5. 是否补一个最小 CI（GitHub Actions 容器跑 pytest）？——审计一发现仓库无 CI，B2 先并入 pytest 流程，CI 单独立项（开放）。

---

## 附：审计记录

**审计一**（事实核对，FAIL 2/WARN 2/PASS 14）：发现仓库无 CI、source_type 枚举无「回款」（正确口径=租金收入）、WBS 天数加总错误——全部修正，报告见 [AUDIT-v1](./AUDIT-2026-08-27-siegpu-ai-assistant-intel-plan-v1.md)。

**审计二**（对抗性设计审查，红 1/黄 5）：发现认知衰减无归因数据源（补 cognition_used 使用痕迹）、确认令牌需原子认领、写动作需角色门槛、铁律措辞冲突、评写过拟合纪律——全部落入 v1.2，报告见 [AUDIT-v2](./AUDIT-2026-08-27-siegpu-ai-assistant-intel-plan-v2.md)。

**终检**：审计修复本身经历一次「假绿」（三引号锚点静默失败），终检阶段以逐行 grep 复核发现并补修——所有审计处置确认落地。

---

## 附 2：实施记录（2026-08-27 全面完成）

| 里程碑 | 状态 | 关键产物 |
|---|---|---|
| M-B 评测闸口 | ✅ | eval.py 分层/归因/报告/限速；test_golden_fastpath.py 并入 pytest；**基线 29/29=100% 四层全达标**（见 eval-baseline-2026-08-27.md） |
| M-A 认知沉淀 | ✅ | 0026 迁移；memory 认知块（召回/强化/衰减/红线/预算）；3 工具；e2e 实测教学→召回→归因全通 |
| M-C 写操作确认卡 | ✅ | 0027 迁移（confirm_tokens + audit CHECK +ASSISTANT_WRITE）；writes.py 四动作八不变量；前端确认卡；默认 flag 关（仅 record_income 白名单待用户拍板放开） |

**实施中额外修复（计划外发现）**：
1. contextvars 在 StreamingResponse threadpool 迭代中跨 yield 丢失 → 认知/写工具收不到用户；改 call_tool 显式注入（needs_user）。
2. reasoning 模型思考耗尽 2048 token 预算 → 空回答；engine 提至 4096 + 空内容重试一次。
3. eval 工具轮耗尽无成文 → 假 text_miss；加强制成文兜底（endpoint 同款）。
4. 连续全量评测触发 provider 分钟级限流 → 题间 2s 限速。
5. writes.py 一处 `.strip}` 符号缺失（应为 `.strip()`）——"同查询不同结果"悬疑的根源，逐字节 od 定位。

**测试**：后端 542 passed（新增 41 项：cognition 15 / writes 10 / golden_fastpath 2 / parity 6 / 其余增强）。
**验收语义修正**：A-1 验收 #1「tools_used 不含 search_projects」过严——认知价值是省澄清往返而非省检索（基线报告有实测证据）。

---

## 附 3：写功能放开记录（2026-08-27 用户拍板「都开了」）

- .env：`ASSISTANT_WRITES_ENABLED=true`，白名单 = 全部四动作（record_income/draft_billing/advance_step/allocate_funds）；compose 已透传两个新变量。
- **e2e 实测全链路**（真实对话）：「帮商机5090登记 66 元回款」→ 工具出卡（record_income/66.0）→ 用户确认 → 落账 `capital_transactions`（租金收入/IN/66.00/备注e2e写测试）→ 双审计（CAPITAL_TXN + ASSISTANT_WRITE 各一行）。
- 放开过程修复三处接线 bug：① needs_user 注入与写工具 lambda 形参冲突（multiple values for 'project_name'）；② lambda 体漏传 user（missing 'params'）；③ 端点 tool 异常路径 result 未初始化（UnboundLocalError 吞掉生成器）。另：卡片下发即 commit 令牌（确认端点另起事务，防跨事务读不到）。
- 安全闸门保持：确认卡 5 分钟过期 / 单次执行 / 日限额 20 / 角色双侧校验 / 双审计。