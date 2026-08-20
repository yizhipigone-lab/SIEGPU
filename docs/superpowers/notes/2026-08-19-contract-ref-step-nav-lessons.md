# SIEGPU 步骤导航 + 采购合同参照 实现经验

> 日期：2026-08-19 · 合并到 main：commit `13a148b`
> 关联：四期 W4 合同深化（前置）、金租分次放款（同波次）

两个功能：① 工作流步骤可点击实体级跳转；② 采购合同参照销售合同（1 对多强联动）。

## 技术设计要点（可复用）

### 采购合同参照销售合同

- **数据模型**：复用 `Contract.parent_contract_id`（自引用外键）表达 1 销售:N 采购，**不改表结构、无迁移**。
- **参照创建后锁定**：`parent_contract_id` 不进 `ContractUpdate` schema 和 `_UPDATEABLE` 白名单——一旦参照某销售合同便不可改挂。
- **三条规则**：
  1. 强制参照：新建采购合同必选同项目 SALES 合同
  2. 采购总额(含税) ≤ 销售额：创建**和编辑**路径都校验，编辑排除自身；SQL 用 `COALESCE(amount_incl_tax, amount)` 按行回退，两侧同口径
  3. 销售变更返回 `referenced_purchase_count`，前端据此弹"请复核采购合同"提示

### 步骤导航实体级跳转

- **后端**：`workflow_service._attach_step_entity_refs` 给 steps 附实体 id，**按步骤 name 匹配**（不用 seq——模板会重编号）；refs 不落库（写路径 `with_refs=False` + strip 防护）。
- **前端**：WorkflowProgress 的 n-step 可点击，单实体直达详情（`?detail=<id>`）、多实体跳过滤列表（`?project_id=&type=`）；GenericCrud 用 `pendingDetailId + items watcher` 处理"列表未加载完时详情先到"的时序。

## 重要工程教训

### 教训 1：worktree 基线必须与功能依赖的代码一致

一开始基于 HEAD 建 worktree，但工作区有 25+ 文件未提交改动（四期 W4），其中 `amount_incl_tax` 字段只存在于未提交改动里。worktree 基于 HEAD 缺这些字段，功能建不下去。

**解决**：先验证并提交前置工作（W4，测试全过），再在新 HEAD 上重建 worktree。

**教训**：建 worktree 前先确认功能依赖的字段/代码是否都在 HEAD 里；不在就先提交前置工作，否则 worktree 隔离反而造成脱节。

### 教训 2：final review 必须端到端，逐任务 review 会漏集成缺陷

逐任务 review 全过，但最终整体 review 抓到 8 个缺陷（2 Critical + 4 Important），全是"逐块验证但没连起来验证"才会漏的：

- **"发射了但没消费"**：步骤导航发出的 `?detail=`/`?project=`/`?type=` 在目标页没人读
- **编辑路径绕过**：cap 只在创建路径校验，编辑路径可绕过
- **持久化泄漏**：步骤 refs 泄漏进 JSONB 并过期
- **发射未消费**：后端发射的 `referenced_purchase_count` 前端没人消费

**教训**：跨模块功能必须做一次端到端整体 review，重点查"谁发射了什么、谁消费了什么"的对账。

### 教训 3：破坏性校验规则会连带破坏既有测试 fixture

"采购合同必须参照销售合同"这条新规则破坏了 W4 里 20 个既有测试（它们创建 PURCHASE 不带 parent）。计划时没预见。

**教训**：加破坏性校验时，要么同步修受影响 fixture，要么规则做软启动。

## 流程记录（subagent-driven）

10 任务计划 → 逐任务 subagent 实现 + spec/quality 两级 review → final review 抓 8 个集成缺陷 → 5 个修复 commit → 复验通过 → 合并。全程 TDD，backend 411 测试全过、frontend 构建成功。
