# SIEGPU 向导式工作台 — 设计计划书 v1.2

> 日期：2026-08-01 | 状态：DRAFT v1.2（二次审计迭代） | 审计：[AUDIT-2026-08-01-wizard-plan.md](./AUDIT-2026-08-01-wizard-plan.md)
> 依赖：[v3.1 全链路设计](./2026-08-01-siegpu-erp-design-v3.md)
> v1.0 → v1.1 变更：6 HIGH 全修 + 5 MEDIUM + 3 LOW，详见 §11.1
> v1.1 → v1.2 变更：步数编号全局统一（18/15 步）、埋点口径统一、异常策略与 T13 矛盾修正、补齐手动完成端点、路由/权限/健壮性细节修正，详见 §11.2

---

## 1. 问题定义与目标

### 1.1 现状痛点

- 用户必须自己记住"下一步该干什么"
- 步骤间数据关联依赖人工
- 进度不可见
- 不同项目路径不同，当前无区分

### 1.2 目标

构建项目工作台——系统引导用户沿流程走，自动推进、一键操作。

---

## 2. 用户需求（已确认）

| # | 需求 |
|---|---|
| R1 | 首页待办推送 + 项目工作台进度页，两者都要 |
| R2 | 流程完全可配置——不同项目可不同步骤集合 |
| R3 | 关键步骤抽屉操作，简单步骤跳转已有页面 |
| R4 | 每步有明确角色归属（执行人+审批人），按角色过滤待办 |
| R5 | 步骤间数据自动传递（上一步产出→下一步预填） |
| R6 | 步骤完成自动检测，进度条实时更新 |
| R7 | 不破坏现有 24 张表 + 72 测试 |

---

## 3. 数据模型（3 张新表）

### 3.1 `workflow_templates` — 流程模板

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(200) | 如"金租直融标准流程" |
| description | TEXT | 适用场景 |
| steps | JSONB | 步骤定义数组（见 §3.4） |
| is_active | BOOLEAN DEFAULT TRUE | |
| created_at / updated_at / deleted_at | TIMESTAMPTZ | |

预置 2 个模板（v1.1 修正：删掉"流贷+金租"——其 18 步与金租直融完全相同，仅参数不同，属同一模板的不同参数化而非不同模板；模板 2 为精简版）：

1. **标准金租流程**（18 步）— 完整链路：自有+流贷垫付→金租置换，步骤全集见 §4
2. **自有资金全款流程**（15 步）— 在 §4 新编号下跳过 Step 6（银行流贷入金）、Step 9（金租申请）、Step 10（金租放款+置换），即 18−3=15。v3.1 旧编号中的"Step 7.1 流贷部分货款"已并入 Step 8 预付采购款（自有全款下该步照常执行，资金来源为自有资金）。v1.1 写"14 步"系沿用 17 步旧编号所致，v1.2 修正为 15 步

### 3.2 `project_workflows` — 项目流程实例

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK→projects, UNIQUE | 1 项目 1 流程 |
| template_id | UUID FK→workflow_templates, nullable | 来源模板 |
| steps | JSONB | 实际步骤列表（从模板深拷贝，可独立调整） |
| current_step | INTEGER DEFAULT 1 | 当前步骤的 **seq**（语义见下） |
| status | VARCHAR(20) | 进行中 / 已完成 / 已暂停 |
| created_at / updated_at / deleted_at | TIMESTAMPTZ | |

> `current_step` 语义：**第一个 status=pending 且 required=true 的步骤的 seq**。查找时必须按 `seq` 匹配 steps 数组元素，不可用数组下标（模板自定义后 seq 可能不连续，见 §5.2）。

### 3.3 `step_audit_logs` — 步骤操作日志

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_workflow_id | UUID FK→project_workflows | |
| step_seq | INTEGER | 步骤序号 |
| step_name | VARCHAR(100) | 步骤名快照 |
| action | VARCHAR(20) | complete / skip / manual_complete / infer；`rollback` 为预留枚举值，v1 无回滚 API |
| operator_id | UUID FK→users | infer 动作记为系统用户或 NULL |
| operated_at | TIMESTAMPTZ | |
| note | TEXT | |

### 3.4 `steps` JSONB 结构

```json
{
  "seq": 6,
  "name": "银行流贷入金",
  "description": "向银行申请流动资金贷款并确认到账",
  "module": "capital",
  "action": "record_transaction",
  "doer_role": "FINANCE_STAFF",
  "approver_role": null,
  "required": true,
  "drawer": true,
  "drawer_schema": "capital_in",
  "prefill": {
    "project_id": "{{project_id}}",
    "source_type": "银行流贷",
    "direction": "IN"
  },
  "context_output": ["capital_transaction_id"],
  "completion_check": {
    "table": "capital_transactions",
    "table_whitelist": true,
    "conditions": {
      "project_id": "{{project_id}}",
      "source_type": "银行流贷",
      "direction": "IN",
      "deleted_at": null
    },
    "min_count": 1
  },
  "action_chain": [],
  "status": "pending",
  "completed_at": null,
  "completed_by": null
}
```

**v1.1 修正字段**：
- `role` → `doer_role` / `approver_role`（分离执行人与审批人，对应 v3.1 §6 权限矩阵）
- `context_output`：本步完成后的产出 ID 列表（如 `["capital_transaction_id"]`），供后续步骤的 `{{prev.capital_transaction_id}}` 引用
- `action_chain`：抽屉多 API 编排列表（如验收=create→upload→approve），`[]` 表示单一 API
- `completion_check.table_whitelist`：文档提示标记，声明该表须在后端白名单内；实际校验以后端常量 `ALLOWED_TABLES` 为准（§5.2），前端不可通过 PATCH 注入白名单之外的表名

---

## 4. 18 步完整映射表

> v1.1 新增、v1.2 更名：每一步到 wizard 元数据的完整映射。这是实现的"真相源"。

| Seq | 步骤名 | module | action | drawer | doer | approver | 推进方式 |
|-----|--------|--------|--------|--------|------|----------|----------|
| 1 | 项目建立 | project | create_project | false | PROCUREMENT | — | **内联标记**（create_workflow 时自动 done） |
| 2 | 销售合同 | contract | create_contract | false | PROCUREMENT | — | 埋点 |
| 3 | 采购合同 | contract | create_contract | false | PROCUREMENT | — | 埋点 |
| 4 | 销售订单 | sales_order | create_sales_order | false | PROCUREMENT | — | 轮询 |
| 5 | 采购订单 | order | create_order | false | PROCUREMENT | — | 轮询 |
| 6 | 银行流贷入金 | capital | record_transaction | true | FINANCE_STAFF | — | 埋点 |
| 7 | 自有资金入金 | capital | record_transaction | true | FINANCE_STAFF | — | 埋点 |
| 8 | 预付采购款 | capital | record_transaction | true | FINANCE_STAFF | — | 埋点(金额足额检测) |
| 9 | 金租申请 | leasing | create_process | false | DELIVERY | — | 轮询 |
| 10 | 金租放款+置换 | leasing | disburse | false | FINANCE_DIRECTOR | FINANCE_DIRECTOR | 埋点 |
| 11 | 采购验收 | acceptance | create+approve | true | PROCUREMENT | FINANCE_DIRECTOR | 埋点 |
| 12 | 交付6阶段 | delivery | advance_stage | false | PROCUREMENT | — | 轮询(检测点亮完成) |
| 13 | 销售验收 | acceptance | create+approve | true | DELIVERY | FINANCE_DIRECTOR | 埋点 |
| 14 | 点亮 | order | light_on | false | PROCUREMENT | — | 埋点 |
| 15 | 计费 | billing | generate_billing | true | FINANCE_STAFF | — | 埋点 |
| 16 | 客户确认 | confirmation | confirm | true | FINANCE_STAFF | — | 埋点 |
| 17 | 开票+回款+核销 | invoice | create+pay+reconcile | true | FINANCE_STAFF | FINANCE_DIRECTOR | 埋点 |
| 18 | 盈利测算 | profit | calculate | false | FINANCE_STAFF | — | 轮询 |

- **埋点 = 8 处 after_action 调用，覆盖 12 步**：Step 2/3（同一 `create_contract`）、Step 6/7/8（同一 `record_transaction`）、Step 10、Step 11/13（同一 `approve_acceptance`）、Step 14、15、16、17
- **轮询 = 前端打开工作台时自动检测**：Step 4/5/9/12/18 — 共 5 步
- **内联标记**：Step 1 — 1 步
- 总计：18 步（比 v3.1 多一步"采购验收"独立于"销售验收"，实际业务拆分后为 18 步）

**实现注意（v1.2 补充）**：
- Step 2/3 共用 `create_contract`、Step 11/13 共用 `approve_acceptance`：completion_check 必须以业务类型字段区分（合同 `type=SALES/PURCHASE`、验收单 `type=采购/销售`），否则一次埋点会误推进另一步
- Step 10 的 doer 与 approver 同为 FINANCE_DIRECTOR，构成**自审批**，与 R4 的"执行人+审批人"分离原则冲突 → 待业务确认（见 §12 风险 9）
- 轮询步骤不做埋点是有意的：这些步骤的"完成"依赖外部状态累积（如交付 6 阶段逐阶段推进），打开工作台时全量 refresh 即可覆盖，无需在每次业务写入时检测

---

## 5. 工作流引擎（Service 层）

### 5.1 决策：同步事务内推进（v1.1 明确，v1.2 补充异常策略）

**选择同步，不异步**。理由：
- `requirements.txt` 无 celery/arq/rq/BackgroundTask
- 同步保证原子性：业务回滚则推进回滚
- 用 `SELECT FOR UPDATE` 锁 project_workflows 行防并发
- 每步多 1 次 completion_check 查询（≈1ms），对写操作可忽略

**异常策略（v1.2 统一，消除与 T13 的矛盾）**：
- **业务操作失败** → 整个事务回滚，推进自然不发生（原子性只在这个方向成立）
- **after_action 自身异常**（如 completion_check 查询失败）→ 捕获、记日志、**不回滚业务操作**。进度滞后由两道兜底修复：打开工作台时强制 refresh（§8.3）+ 手动标记完成 API（§6）。此策略与 T13 一致

### 5.2 `workflow_service.py` — 核心函数

```python
# —— 创建与查询 ——
def create_workflow(db, *, project_id, template_id=None):
    """从模板深拷贝 steps，自动标记 Step 1 完成。"""
    # 1) 深拷贝模板 steps 到 project_workflows
    # 2) steps[seq=1].status = "done", completed_at = now()
    # 3) current_step = 第一个 status=pending 且 required=true 的步骤 seq
    # 4) 写 step_audit_log(action=complete, seq=1)

def get_workflow(db, project_id) -> ProjectWorkflow | None:
    """获取项目流程，不存在则尝试推断生成（旧项目兼容，见 §8）。推断幂等。"""

def get_my_tasks(db, user_id):
    """首页待办：查找 current_step.doer_role == user.role 的 pending 步骤。
    v1 范围说明：只推 doer 待办；approver 的待审批事项由现有审批队列承担，
    不在本接口返回（是否纳入 v2 待确认，见 §12 风险 9）。"""

# —— 推进 ——
def after_action(db, project_id):
    """在业务操作成功后调用（同步，同一事务）。SELECT FOR UPDATE 锁行。
    内部 try/except：推进失败记日志，不向调用方抛（见 §5.1 异常策略、T13）。"""
    wf = get_workflow_for_update(db, project_id)  # SELECT FOR UPDATE
    if not wf:
        return
    # 按 seq 查找，不用数组下标——模板自定义后 seq 可能不连续
    current = next((s for s in wf.steps if s["seq"] == wf.current_step), None)
    if current and check_completion(db, project_id, current):
        mark_done(wf, current, db)
        wf.current_step = find_next_required(wf.steps, current["seq"])

def check_completion(db, project_id, step):
    """根据 completion_check 查询检测步骤是否完成。table 名白名单校验。"""
    table = step["completion_check"]["table"]
    if table not in ALLOWED_TABLES:  # 白名单：业务表集合
        raise ValueError(f"table {table} not in whitelist")
    conditions = resolve(step["completion_check"]["conditions"], project_id)
    count = db.execute(select(func.count()).select_from(table(table)).where(*conditions)).scalar()
    return count >= step["completion_check"].get("min_count", 1)

def refresh_all_steps(db, project_id):
    """全量重检：从头到尾检测每步完成状态（轮询用 + 手动刷新）。
    支持回退：已 done 的步骤若检测不再满足（如红冲），置回 pending，
    current_step 同步回退到第一个 pending 且 required 的步骤 seq（对应 T14）。
    skip 为终态，不参与回退（对应 T5）。"""

# —— 手动控制 ——
def skip_step(db, project_id, seq, reason, operator_id):
    """跳过步骤。权限分级：required=false 步骤 doer 本人可跳过；
    required=true 强制跳过需 FINANCE_DIRECTOR+（见 §6）。"""

def mark_step_done(db, project_id, seq, note, operator_id):
    """手动标记完成（兜底通道，写 audit_log action=manual_complete）。
    需 FINANCE_DIRECTOR+。用于 after_action 静默失败后的进度修复（§12 风险 2）。"""

def update_step_config(db, project_id, seq, **kwargs):
    """调整步骤配置。仅 ADMIN 可调。需 require_role('ADMIN')。"""

# —— 旧项目兼容 ——
def infer_workflow(db, project_id):
    """从 24 张业务表反推进度。幂等：已有记录则直接返回。详见 §8。"""
```

### 5.3 埋点位置（8 处，覆盖 12 步）

每个埋点固定在函数末尾、`db.flush()` 之后、return 之前，仅一行：

```python
from app.services import workflow_service as wf
wf.after_action(db, project_id)
```

| 埋点目标 | 文件:函数 | 覆盖步骤 | project_id 来源 |
|----------|----------|---------|----------------|
| contract_service.create_contract | contract_service.py:68 return 前 | 2, 3 | 参数 `project_id` |
| capital_service.record_transaction | capital_service.py:157 return 前 | 6, 7, 8 | kw["project_id"] |
| leasing_service.disburse | leasing_service.py:134 return 前 | 10 | proc.project_id（从 process 反查） |
| acceptance_service.approve_acceptance | acceptance_service.py:67 return 前 | 11, 13 | ar.project_id |
| order_service.light_on | order_service.py:110 return 前 | 14 | o.project_id |
| billing_service.generate_billing | billing_service.py:56 return 前 | 15 | o.project_id |
| confirmation_service.confirm | confirmation_service.py:65 return 前 | 16 | sc.sales_order 反查 project_id |
| invoice_service.reconcile_invoice | invoice_service.py:172 return 前 | 17 | inv.contract.project_id |

> 注意：capital_service 有多处 `db.flush()`，after_action 只加在最外层 `record_transaction` 的 return 之前，不被内部子调用触发。

### 5.4 并发保护

```python
def get_workflow_for_update(db, project_id):
    return db.execute(
        select(ProjectWorkflow)
        .where(ProjectWorkflow.project_id == project_id)
        .with_for_update()  # 行锁，防并发双推进
    ).scalar_one_or_none()
```

---

## 6. API 端点

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/api/workflows/my-tasks` | 首页待办（按当前用户角色过滤） | 登录 |
| GET | `/api/workflows/templates` | 列出流程模板 | 登录 |
| POST | `/api/workflows/templates` | 创建自定义模板 | ADMIN only |
| GET | `/api/workflows/{project_id}` | 获取项目流程（无记录时自动推断，见 §8） | 登录 |
| POST | `/api/workflows/{project_id}/refresh` | 全量刷新步骤状态（含回退检测） | 登录 |
| POST | `/api/workflows/{project_id}/skip/{seq}` | 跳过步骤 | 见下方权限分级 |
| POST | `/api/workflows/{project_id}/steps/{seq}/complete` | 手动标记完成（兜底，v1.2 新增） | FINANCE_DIRECTOR+ |
| PATCH | `/api/workflows/{project_id}/steps/{seq}` | 调整步骤配置 | ADMIN only |

**路由与权限注意（v1.2 补充）**：
- `/api/workflows/my-tasks` 与 `/api/workflows/templates` 必须在 `/api/workflows/{project_id}` **之前声明**，且 `{project_id}` 路径参数声明为 UUID 类型——否则 "my-tasks" 会被当作 project_id 捕获
- skip 权限分级：`required=false` 的步骤，该步 doer 角色即可跳过；`required=true` 的步骤强制跳过需 FINANCE_DIRECTOR+。两种情形都必须带 `reason` 并写 audit_log
- GET `/{project_id}` 首次访问会触发 infer 落库（一次写入），属有意设计；infer 幂等，重复调用安全

---

## 7. 前端设计

### 7.1 首页待办卡片（Dashboard.vue 扩展）

调用 `GET /api/workflows/my-tasks` → 渲染待办卡片列表。每张卡片显示：项目名、步骤名、角色、[立即处理] 按钮。
- `drawer=true` → 在当前页弹出 StepDrawer
- `drawer=false` → `router.push` 跳转到对应模块页

### 7.2 项目工作台（ProjectWorkspace.vue — 新增）

路由：`/projects/:id/workspace`

三栏布局：
- **顶栏**：进度条（N 步圆点，N 随项目模板而定，绿=done / 蓝=current / 灰=pending / 黄=skipped）
- **左栏**：步骤时间线（点击跳转）
- **右栏**：操作区——当前步骤抽屉或模块跳转按钮

打开工作台时自动调用 `POST /refresh`，保证轮询类步骤与回退检测（红冲）即时生效。

### 7.3 通用抽屉（StepDrawer.vue）

注册表模式（非真 schema 驱动，措辞修正）：

```typescript
const drawerComponents: Record<string, Component> = {
  capital_in: CapitalInForm,
  capital_out: CapitalOutForm,
  acceptance: AcceptanceForm,       // action_chain: create→upload→approve
  billing_confirm: BillingConfirm,
  confirmation: ConfirmationUpload,
  invoice_issue: InvoiceIssueForm,
}
```

- `acceptance` 抽屉的实现：3 步链式调用——先 `POST /acceptances` 创建 → `POST /files/acceptances/{id}/upload` 上传 → `POST /acceptances/{id}/approve` 通过。任一步失败回滚（前端乐观处理 + 后端事务保证）
- `AcceptanceForm` 通过 prop 传入验收类型（采购/销售），供 Step 11 / Step 13 复用同一组件（v1.2 补充）

### 7.4 路由与侧边栏

- 路由：`/projects/:id/workspace` → `ProjectWorkspace.vue`
- 项目列表每行增加"工作台"链接按钮
- 侧边栏不变（工作台从项目进入，不独立菜单）

---

## 8. 旧项目兼容（存量数据迁移）

> v1.1 新增独立章节。这是 v1.0 最大的遗漏风险。

### 8.1 触发时机

`get_workflow(project_id)` 发现 project_workflows 表无记录时，自动调用 `infer_workflow`。推断**幂等**：已有记录直接返回，重复触发安全。

### 8.2 推断规则（逐步骤）

从 24 张现有业务表反推，复用各步的 `completion_check` 规则（与 §4 同一真相源，不另写一套逻辑）：

```
Step 1  项目建立        → projects 表有记录                    → done
Step 2  销售合同        → contracts(type=SALES, project_id)    → count≥1 → done
Step 3  采购合同        → contracts(type=PURCHASE, project_id)  → count≥1 → done
Step 4  销售订单        → sales_orders(project_id)             → count≥1 → done
Step 5  采购订单        → orders(project_id)                   → count≥1 → done
Step 6  银行流贷入金    → capital_transactions(source_type=银行流贷, IN) → count≥1 → done
...（逐步骤同 completion_check 规则）
Step 18 盈利测算        → profit_scenarios(is_actual=true, project_id) → count≥1 → done
```

### 8.3 兜底策略

- 推断到第一个 `status=pending` 的步骤为 `current_step`
- 如果所有步骤都已是 done → `current_step=18, status=已完成`
- 部分中间步骤数据缺失（如跳跃操作）→ 标记 `status=pending`，用户可手动 skip 或补做
- 提供 `POST /workflows/{project_id}/refresh` 手动重新推断
- 推断动作写 audit_log（action=infer），便于事后追溯"进度是推断出来的还是真实推进的"

---

## 9. 实现计划（5 个 Phase）

> v1.1 Phase 2 拆分为 2a/2b/2c

### Phase 1：数据层
- 3 个新 model（workflow_template / project_workflow / step_audit_log）
- 更新 schema.sql（+3 DDL）
- 更新 models/__init__.py
- Alembic 0003 增量迁移
- 3 个 Pydantic schema

### Phase 2a：引擎核心（低风险新代码）
- workflow_service（create/get/check_completion/refresh/skip/mark_step_done/infer_workflow）
- workflow_template_service（模板 CRUD）
- 配套单元测试（14 条，见 §10）

### Phase 2b：API 层（薄路由）
- 8 个端点（§6）
- 所有变更类端点挂 `require_role`
- PATCH steps 加 table 名白名单校验
- 注意 §6 的路由声明顺序要求

### Phase 2c：埋点（高风险，独立提交）
- 在 8 个现有 service 函数中各加 1 行 `wf.after_action(db, project_id)`
- 独立集成测试（3 条）验证埋点触发正确
- **这个 Phase 出问题直接 revert，不影响 2a/2b 的核心功能**

### Phase 3：前端
- `ProjectWorkspace.vue`（项目工作台）
- `StepDrawer.vue` + 6 个 form 组件
- `Dashboard.vue` 待办卡片区域
- 路由更新

### Phase 4：种子数据 + E2E + 最终验证
- seed：预置 2 个 workflow_templates 的完整 steps JSON（18 步 / 15 步）
- demo 扩写：展示向导式流程推进
- E2E（3 个 spec）：工作台进度条 / 抽屉预填+提交 / 首页待办
- **现有 72 测试必须全绿**

---

## 10. 测试策略

> v1.1 具体化：从"8+ 用例"改为 14 条断言清单

### 单元测试（14 条，Phase 2a 同批交付）

| # | 用例 | 验证点 |
|---|---|---|
| T1 | create_workflow | 深拷贝 steps，改项目不污染模板 |
| T2 | create_workflow 自动标记 Step 1 | status=done, current_step=2 |
| T3 | after_action 跳过 required=false | 推进到下一个 required 步 |
| T4 | after_action 末尾无 next | 状态置"已完成"不抛错 |
| T5 | skip_step 后 refresh 不复活 | skip 为终态 |
| T6 | 乱序完成检测 | 先做 Step 15 再做 Step 5，refresh 均识别 |
| T7 | get_my_tasks 按 doer_role 过滤 | 只返回匹配步骤 |
| T8 | get_my_tasks 空角色 | 不抛错，返回空 |
| T9 | after_action 并发只推进一次 | SELECT FOR UPDATE 串行化 |
| T10 | completion_check table 白名单 | 非法表名抛 ValueError |
| T11 | PATCH steps 非 ADMIN 拒绝 | 403 |
| T12 | infer_workflow 旧项目推断 | 从已有数据推断进度正确；重复调用幂等 |
| T13 | after_action 失败不影响业务 | 异常被捕获记日志，业务提交不回滚（§5.1） |
| T14 | 红冲后 refresh 检测状态回退 | 资金被红冲→对应步骤变回 pending，current_step 回退 |

### 集成测试（3 条，Phase 2c 交付）

| # | 流程 | 验证点 |
|---|---|---|
| I1 | 标准金租 18 步全流程 | 每步触发→检测完成→自动推进 |
| I2 | 自有全款 15 步 | skip 步骤不参与推进 |
| I3 | 自定义流程 | 修改 steps（含 seq 不连续）后按 seq 查找推进正确 |

### E2E（3 个 spec，Phase 4 交付）

- 工作台进度条随操作推进
- 验收抽屉链式提交（create→upload→approve）
- 首页待办按角色显示/过滤

### 回归基线

**72 现有测试全绿**——任何 Phase 提交前必跑。

---

## 11. 变更摘要

### 11.1 v1.0 → v1.1

| # | 变更 | 对应审计项 |
|---|---|---|
| 1 | after_action 明确同步事务内执行，删掉"异步"方案 | H1 |
| 2 | create_workflow 内自动标记 Step 1 done | H2 |
| 3 | 新增 §4 "完整映射表"，明确埋点/轮询/内联分工 | H3 |
| 4 | PATCH steps 加 table 白名单 + require_role(ADMIN) | H4 |
| 5 | after_action 加 SELECT FOR UPDATE 行锁 | H5 |
| 6 | 新增 §8 "旧项目兼容"独立章节（推断规则 + 兜底策略） | H6 |
| 7 | 模板 2 从"约 10 步"修正（v1.1 写 14 步，v1.2 再修正为 15 步） | M7 |
| 8 | role 拆分为 doer_role + approver_role | M8 |
| 9 | 新增 context_output / {{prev.xxx}} 跨步骤 ID 传递 | M10 |
| 10 | 新增 action_chain 定义抽屉多 API 编排 | M11 |
| 11 | Phase 2 拆为 2a/2b/2c | 优先级建议 |
| 12 | 测试从"8+ 用例"改为 14 条断言清单 | 可测试性 |
| 13 | seq 示例修正（银行流贷从 seq:1 改为 seq:6） | L12 |
| 14 | "schema 驱动"措辞修正为"注册表模式" | L13 |
| 15 | 新增红冲与状态回退测试用例 T14 | M9 |

### 11.2 v1.1 → v1.2（本次审计）

| # | 变更 | 类型 |
|---|---|---|
| 1 | 步数编号全局统一：§4 标题 17→18 步；模板 1 为 18 步、模板 2 为 15 步（18−3，跳过 Step 6/9/10，旧编号 Step 7.1 已并入 Step 8）；I2、Phase 4 同步修正 | 一致性 |
| 2 | 埋点口径统一为"8 处埋点覆盖 12 步"：§4 汇总、§5.3 标题与表格（补"覆盖步骤"列）、Phase 2c 测试数 4→3（与 §10 集成测试 3 条一致） | 一致性 |
| 3 | §5.1 异常策略统一：业务失败整体回滚；after_action 失败吞异常记日志不阻断业务——消除与 T13 的矛盾 | 矛盾修正 |
| 4 | 新增 `POST .../steps/{seq}/complete` 手动标记完成端点 + `mark_step_done` 函数，补齐 §12 风险 2 引用的兜底 API；端点数 7→8，与 Phase 2b 描述一致 | 缺口 |
| 5 | after_action 按 `seq` 查找步骤而非数组下标；§3.2 明确 current_step 语义；I3 增加 seq 不连续验证 | 健壮性 |
| 6 | §6 路由声明顺序：`/my-tasks`、`/templates` 须在 `/{project_id}` 之前，且 project_id 为 UUID 类型 | 缺陷 |
| 7 | skip 权限分级：required=false 由 doer 跳过，required=true 需 FINANCE_DIRECTOR+；消除 §5.2 与 §6 的矛盾 | 一致性 |
| 8 | refresh_all_steps 明确回退语义（done→pending 且 current_step 回退、skip 为终态），与 T5/T14 对齐 | 明确 |
| 9 | Step 10 自审批（doer=approver=FINANCE_DIRECTOR）标记为待业务确认；Step 11/13 需在 completion_check 以验收类型区分；get_my_tasks v1 仅 doer 待办，审批待办归属现有审批队列 | 待确认 |
| 10 | infer_workflow 幂等性说明；推断动作写 audit_log（action=infer）；audit_log action 枚举补 manual_complete/infer，rollback 标注为预留 | 明确 |

---

## 12. 风险与缓解

| # | 风险 | 级别 | 缓解 |
|---|---|---|---|
| 1 | 旧项目进度推断错误 | HIGH | 单独 §8 推断规则 + 人工确认兜底 + 手动 refresh API |
| 2 | after_action 静默失败致进度停滞 | HIGH | 前端打开工作台强制 refresh + 手动标记完成 API（§6）兜底 |
| 3 | 并发双推进 | HIGH | SELECT FOR UPDATE 行锁（§5.4） |
| 4 | completion_check 越权 | HIGH | table 白名单（§5.2）+ PATCH require_role(ADMIN)（§6） |
| 5 | 红冲/撤销导致状态脱节 | MEDIUM | T14 测试覆盖 + refresh 可检测回退 + 手动 skip 兜底 |
| 6 | 模板×18步映射工作量大 | MEDIUM | §4 已逐条列出，实现期直接照表翻译 |
| 7 | 埋点污染现有测试 | MEDIUM | Phase 2c 独立提交 + 可独立 revert |
| 8 | 前端抽屉链式调用失败 | MEDIUM | 后端事务保证原子性 + 前端乐观回滚 |
| 9 | Step 10 自审批违背职责分离；审批人待办无推送通道 | MEDIUM | **待业务确认**：Step 10 的 doer 是否应改为 FINANCE_STAFF；审批待办是否纳入 my-tasks（v2） |

---

> **下一步**：计划书已经两轮审计迭代（v1.1：6 HIGH + 5 MEDIUM + 3 LOW；v1.2：10 项一致性/缺口修正）。§12 风险 9 待业务确认后进入实现。
