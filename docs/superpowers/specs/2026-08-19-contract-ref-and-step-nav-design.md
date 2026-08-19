# 步骤导航实体级跳转 + 采购合同参照销售合同 设计文档

- 日期：2026-08-19
- 状态：草案（待用户 review）
- 项目：SIEGPU（算力租赁 ERP，FastAPI + Vue3 + PostgreSQL 16）
- 关联：金租分次放款（1 销售合同 : N 采购合同 的业务前提）

## 1. 背景与目标

两个围绕「项目工作流 + 合同关系」的增强，源自订单详情页（截图：顶部 Step 1-5 导航 + 交付阶段）的使用反馈。

**问题 A：步骤导航不可点击。** 订单/合同详情抽屉顶部的 Step 1-5（项目建立/销售合同/采购合同/批次订单/设备导入）目前纯展示，用户期望点击步骤名直接跳到对应实体。

**问题 B：采购合同与销售合同无关联。** 业务上采购合同（成本侧）应该参照某份销售合同（收入侧）建立，形成 1 对多强联动关系。

目标：

- A：步骤导航可点击，实体级精确跳转（点"销售合同"直达该项目那份销售合同详情）。
- B：采购合同强制参照销售合同（1 销售 : N 采购），带总额硬校验与变更复核提示。

## 2. 现状分析（已核实）

### 2.1 步骤导航（问题 A）

- 渲染组件：`frontend/src/components/WorkflowProgress.vue`，由 `GenericCrud.vue` 在实体带 `project_id` 时挂载（详情抽屉顶部）。
- 数据源：`GET /workflows/{project_id}` → `{ steps, current_step, status }`，每个 step 含 `seq/name/status/doer_role/drawer_schema`（**无实体 id**）。
- 当前 `n-step` 只读，无点击。
- 步骤→实体的映射在 `frontend/src/utils/roleGuide.ts` 已有（seq 1→项目、seq 2→销售合同、seq 3→采购合同、seq 4→批次订单、seq 5-7→设备）。

### 2.2 合同关系（问题 B）

- `backend/app/models/project.py` 的 `Contract`：**`parent_contract_id`（自引用外键到 `contracts.id`）与 `type`（SALES/PURCHASE）已存在**，无需改表结构。
- demo 数据（`demo.py`）已使用：`purchase_contract.parent_contract_id = sales_contract.id`（"销售合同 parent + 采购子合同级联"）。
- `Contract.amount` 为不含税口径，`amount_incl_tax` 为含税口径（nullable，存量可为 NULL）。
- 当前创建采购合同**不强制**选择参照销售合同，也无总额校验、无变更复核。

## 3. 设计：步骤导航实体级跳转（问题 A）

### 3.1 后端：`GET /workflows/{project_id}` 步骤附实体引用

在每个 step 的返回 dict 上追加可选实体 id 字段（只读查询，不改变工作流状态机）：

| step.seq | 附加字段 | 取值逻辑 |
|---|---|---|
| 1 项目建立 | （`project_id` 路由参数本身，前端已有） | — |
| 2 销售合同 | `sales_contract_id` | 该项目 `type=SALES` 的合同，取最早一份（多份时前端跳列表） |
| 3 采购合同 | `purchase_contract_id` | 该项目 `type=PURCHASE` 的合同，取最早一份（多份时前端跳列表） |
| 4 批次订单 | `order_id` | 该项目 `orders` 取最早一份 |
| 5+ 设备导入等 | 无（多台设备） | 前端跳设备列表（按 project 过滤） |

> 实现位置：`app/services/workflow_service.py` 的 `get_workflow`（或 `infer_workflow` 序列化 steps 处），在返回前按 project_id 查 contracts/orders 补实体 id。**单实体跳详情、多实体跳列表**的规则放前端，后端只需给出"该类型实体是否存在及其 id"。多份时后端可只给第一份 id 并把 `*_count` 一并返回，前端据此决定跳详情还是列表。

### 3.2 前端：`WorkflowProgress.vue` 可点击

- `n-step` 渲染为可点样式（cursor: pointer + hover 高亮），点击按映射跳转（vue-router `router.push`）。
- 跳转目标：
  - Step 1 → 项目工作台（当前 project，已有 project_id）
  - Step 2 → 销售合同：单份跳详情（`/master/contracts` + 打开该 id 详情），多份跳列表（按 project + SALES 过滤）
  - Step 3 → 采购合同：同上（PURCHASE）
  - Step 4 → 批次订单：单份跳详情，多份跳 `/orders`（按 project 过滤）
  - Step 5+ → `/devices`（按 project 过滤）
- 未开始且无对应实体的步骤置灰不可点；已完成/进行中有实体的步骤可点。
- 详情抽屉跳详情：用路由 query（如 `?detail=<id>`）让目标页打开对应实体的详情抽屉，避免嵌套抽屉。

### 3.3 前端：合同列表支持 project + type 过滤定位

`/master/contracts` 列表页支持 `?project=<id>&type=SALES|PURCHASE` query，进入即过滤，便于步骤跳转后的落地。

## 4. 设计：采购合同参照销售合同（问题 B）

### 4.1 数据模型

**复用现有 `Contract.parent_contract_id`**，不改表结构、无需迁移（Alembic 无需新增）。1 对多由"多份采购合同的 parent 指向同一销售合同"天然表达。

### 4.2 三条规则

**规则 1：强制参照。** 新建/编辑 `type=PURCHASE` 合同时，`parent_contract_id` 必选，候选 = 同 `project_id` 且 `type=SALES` 的合同（前端下拉 + 后端校验双保险）。type=SALES 的合同不要求 parent。编辑存量无 parent 的采购合同时要求补选。

**规则 2：总额硬校验（含税口径）。** 保存采购合同时校验：

```
Σ(同 parent_contract_id 下所有采购合同 amount_incl_tax，编辑时排除自身)
  + 本份 amount_incl_tax
  ≤ 销售合同.amount_incl_tax
```

- 超过 → **禁止保存**，返回错误：`超过销售合同额度：已用 X + 本份 Y > 销售额 Z`。
- **口径与空值**：统一用含税 `amount_incl_tax` 对比。若销售合同 `amount_incl_tax` 为 NULL，退回用其 `amount`（不含税）作上限，且采购合同侧同样用 `amount` 对比（保持同侧口径一致）；若某份采购合同 `amount_incl_tax` 为 NULL，同样退回其 `amount`。校验在服务层 `contract_service.create_contract` / 更新路径执行。
- 仅对 `type=PURCHASE` 且设了 `parent_contract_id` 的合同校验。

**规则 3：变更复核提示。** 销售合同金额（amount/amount_incl_tax）或关键条款变更保存后：
- 后端在响应里带 `referenced_purchase_count`（该销售合同被参照的采购合同数）。
- 前端 toast：`该销售合同已被 N 份采购合同参照，请复核采购合同`，并在销售合同详情页显示警示条。
- **不做**自动联动终止/自动改采购合同（用户已确认排除）。

### 4.3 展示

- **采购合同详情**：显示"参照销售合同：{销售合同号/名称}"，可点跳转该销售合同详情。
- **销售合同详情**：显示"被参照的采购合同（N 份）"列表（合同号 + 金额 + 状态），每行可点跳转。
- 列表页（`/master/contracts`）：可加"参照合同"列（采购合同显示其 parent 合同号），便于浏览。

### 4.4 后端改动点

| 文件 | 改动 |
|---|---|
| `app/services/contract_service.py` | create/update 路径：强制参照校验（PURCHASE 必带同项目 SALES parent）+ 总额硬校验（含税口径）+ 销售合同变更后返回 referenced_purchase_count |
| `app/schemas/contract.py` | 响应增加 `parent_contract_no`（展示用）、`referenced_purchase_count`（销售合同） |
| `app/services/workflow_service.py` | workflow steps 附 sales/purchase/order 实体 id（问题 A） |
| `app/api/v1/endpoints/`（合同相关） | 透传新校验错误码与字段 |

### 4.5 前端改动点

| 文件 | 改动 |
|---|---|
| `WorkflowProgress.vue` | n-step 可点 + 实体级跳转（问题 A） |
| `GenericCrud.vue` / 合同表单 | 采购合同加"参照销售合同"必选下拉（同项目 SALES）；采购详情显示参照合同链接；销售详情显示被参照采购合同列表 + 变更警示条 |
| `config/modules.ts` | 合同模块字段配置：parent_contract 字段 + 列表"参照合同"列 |
| 合同列表视图 | 支持 `?project=&type=` 过滤（问题 A 落地） |

## 5. 数据流

**问题 A（步骤跳转）**：

```
详情抽屉 WorkflowProgress → GET /workflows/{project_id}
  → 后端按 project 查 contracts/orders 补 sales_contract_id / purchase_contract_id / order_id
  → 前端 n-step 点击 → router.push 到对应实体详情/列表
```

**问题 B（保存采购合同）**：

```
表单提交(PURCHASE + parent_contract_id)
  → 后端: 校验 parent 存在且为同项目 SALES（强制参照）
  → 校验 Σ采购 amount_incl_tax(除自身) + 本份 ≤ 销售 amount_incl_tax（总额）
  → 通过则保存；超限返回 4xx + 已用/剩余额度
```

## 6. 错误处理

- 采购合同未选 parent（PURCHASE）→ 400："采购合同必须选择参照的销售合同"
- parent 不是同项目 / 不是 SALES → 400："参照合同必须是本项目的销售合同"
- 总额超限 → 400/409："超过销售合同额度：已用 X + 本份 Y > 销售额 Z"
- 销售合同无含税金额且不含税金额也无 → 视为无上限，跳过校验并提示（避免误拦存量数据）
- 步骤跳转目标实体不存在（如合同被删）→ 前端 fallback 跳列表页

## 7. 测试

- 后端（pytest）：
  - 强制参照：PURCHASE 无 parent 拒绝；parent 跨项目/非 SALES 拒绝
  - 总额校验：N 份采购合计超销售额拒绝（含编辑排除自身、含税/不含税口径回退、NULL 处理）
  - 销售变更返回 referenced_purchase_count
  - workflow steps 返回 sales/purchase/order 实体 id
- 前端（人工 + e2e）：
  - 步骤导航点击 → 各实体正确跳转；多实体跳列表；无实体置灰
  - 采购合同表单必选销售合同；超限保存被拦且提示额度
  - 销售详情显示被参照采购列表；采购详情可跳销售
- 兼容性：存量无 parent 的采购合同不破坏（编辑时才要求补）；demo.py 的级联数据不受影响

## 8. 不做的事（YAGNI）

- ❌ 不自动联动终止采购合同（销售终止时只提示复核，不自动改采购）
- ❌ 不做多对多（一份采购参照多份销售）
- ❌ 不做销售合同金额自动随采购调整（联动只到"提示复核"）
- ❌ 不改表结构/不加 Alembic 迁移（复用 parent_contract_id）
- ❌ 步骤导航不做"跳到流程模板编辑"（只跳业务实体）

## 9. 风险与开放问题

1. **存量采购合同无 parent**：规则 1 只对新建强制；存量编辑时要求补选。是否需要一个数据补录脚本把存量采购合同按项目关联到销售合同？（默认不自动，避免误关联；由用户在编辑时补）
2. **多份销售合同**：一个项目若有多份 SALES 合同，步骤"销售合同"跳列表；采购参照时需人工选对那份（候选下拉已限定同项目 SALES）。
3. **总额口径**：含税对比为主，NULL 回退不含税——已在 §4.2 明确，避免存量 NULL 数据被误拦。
