# 步骤导航实体级跳转 + 采购合同参照销售合同 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① 订单/合同详情抽屉顶部的工作流步骤（Step 1-5）可点击并实体级精确跳转到对应项目/销售合同/采购合同/批次订单/设备；② 采购合同强制参照同项目销售合同（1 对多，创建后锁定），采购总额（含税）≤ 销售合同额（超则禁存），销售变更提示复核。

**Architecture:** 后端 FastAPI + SQLAlchemy 复用现有 `Contract.parent_contract_id`（不改表、无迁移）；`contract_service.create_contract` 加强制参照 + 总额硬校验，`update_contract` 检测金额变更返回参照计数；`workflow_service.get_workflow` 为步骤补实体 id。前端 Vue3 + naive-ui：`WorkflowProgress.vue` 的 n-step 加点击跳转；合同表单（配置驱动 `modules.ts`）加"参照销售合同"动态下拉；详情抽屉展示参照/被参照关系。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Pydantic / pytest（后端单测）；Vue 3 / TypeScript / naive-ui / vue-router（前端）。

**设计决策（已确认）:** 1 销售 : N 采购；参照创建后锁定（`parent_contract_id` 不进 ContractUpdate 与 `_UPDATEABLE`）；强制参照 + 采购总额≤销售额（含税口径，NULL 回退不含税）+ 销售变更提示复核（不自动联动终止）；实体级跳转；总额超限禁止保存。

---

## Task 1: 后端——强制参照校验（create_contract）

**Files:**
- Modify: `backend/app/services/contract_service.py`（create_contract，party 校验后加参照校验）
- Test: `backend/app/tests/test_contract_reference.py`

- [ ] **Step 1: 写失败测试**

Create `backend/app/tests/test_contract_reference.py`:

```python
"""采购合同参照销售合同：强制参照 + 总额硬校验。"""
import uuid
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.master import Customer, Supplier
from app.models.project import Contract, Project
from app.services import contract_service as svc


def _proj(db):
    p = Project(name=f"p{uuid.uuid4().hex[:6]}", status="进行中")
    db.add(p); db.flush()
    return p


def _party(db):
    c = Customer(name=f"c{uuid.uuid4().hex[:6]}")
    s = Supplier(name=f"s{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add_all([c, s]); db.flush()
    return c, s


def _sales(db, proj, cust, incl=Decimal("1000")):
    return svc.create_contract(db, project_id=proj.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"), amount_incl_tax=incl)


def test_purchase_requires_sales_parent(db):
    proj = _proj(db); cust, sup = _party(db)
    with pytest.raises(BusinessError) as e:
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("100"), tax_rate=Decimal("0.13"), amount_incl_tax=Decimal("110"))
    assert "参照" in str(e.value)


def test_parent_must_be_same_project_sales(db):
    proj = _proj(db); cust, sup = _party(db)
    other = _proj(db)
    sales_other = svc.create_contract(db, project_id=other.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"), amount_incl_tax=Decimal("1000"))
    with pytest.raises(BusinessError):
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("100"), tax_rate=Decimal("0.13"),
            amount_incl_tax=Decimal("110"), parent_contract_id=sales_other.id)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: FAIL（第一个用例：PURCHASE 无 parent 目前能创建，不报错）

- [ ] **Step 3: 实现强制参照校验**

Modify `backend/app/services/contract_service.py`，在 `create_contract` 的 party 校验（第 25-31 行）之后、`c = Contract(...)` 之前插入：

```python
    # 采购合同必须参照同项目的一份销售合同（1 销售 : N 采购，创建后锁定）
    if type == "PURCHASE":
        if not parent_contract_id:
            raise BusinessError("BAD_REQUEST", "采购合同必须选择参照的销售合同", 400)
        parent = db.get(Contract, parent_contract_id)
        if not parent or parent.deleted_at is not None:
            raise BusinessError("BAD_REQUEST", "参照的销售合同不存在", 400)
        if parent.project_id != project_id:
            raise BusinessError("BAD_REQUEST", "参照的销售合同必须属于本项目", 400)
        if parent.type != "SALES":
            raise BusinessError("BAD_REQUEST", "参照合同必须是销售合同", 400)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: PASS（2 tests）

- [ ] **Step 5: Commit**

```bash
git -C E:\1target\SIEGPU add backend/app/services/contract_service.py backend/app/tests/test_contract_reference.py
git -C E:\1target\SIEGPU commit -m "feat(backend): 采购合同强制参照同项目销售合同（创建后锁定）"
```

---

## Task 2: 后端——采购总额硬校验（含税口径）

**Files:**
- Modify: `backend/app/services/contract_service.py`（加 `_incl_amount` 辅助 + create 时总额校验）
- Test: `backend/app/tests/test_contract_reference.py`（追加用例）

- [ ] **Step 1: 追加失败测试**

Append to `backend/app/tests/test_contract_reference.py`:

```python
def test_purchase_total_capped_by_sales(db):
    proj = _proj(db); cust, sup = _party(db)
    sales = _sales(db, proj, cust, incl=Decimal("1000"))
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("500"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("600"), parent_contract_id=sales.id)
    with pytest.raises(BusinessError) as e:
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("500"), tax_rate=Decimal("0.13"),
            amount_incl_tax=Decimal("500"), parent_contract_id=sales.id)
    assert "额度" in str(e.value) or "超过" in str(e.value)


def test_purchase_total_fallback_to_net_amount(db):
    """销售合同无含税金额时退回不含税口径对比。"""
    proj = _proj(db); cust, sup = _party(db)
    sales = svc.create_contract(db, project_id=proj.id, type="SALES", party_id=cust.id,
        amount=Decimal("1000"), tax_rate=Decimal("0.13"), amount_incl_tax=None)
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("800"), tax_rate=Decimal("0.13"),
        amount_incl_tax=None, parent_contract_id=sales.id)
    with pytest.raises(BusinessError):
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("300"), tax_rate=Decimal("0.13"),
            amount_incl_tax=None, parent_contract_id=sales.id)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: 前两个 PASS，后两个 FAIL（目前无总额校验）

- [ ] **Step 3: 实现总额硬校验**

Modify `backend/app/services/contract_service.py`。在文件顶部 import 后加辅助函数，并在 `create_contract` 的 PURCHASE 参照校验块内（Task 1 所加，"参照合同必须是销售合同"之后）追加总额校验：

```python
def _incl_amount(c) -> Decimal | None:
    """合同的对比口径金额：优先含税 amount_incl_tax，NULL 退回不含税 amount。"""
    if c.amount_incl_tax is not None:
        return c.amount_incl_tax
    return c.amount
```

在参照校验块末尾（`if parent.type != "SALES": ...` 之后）追加：

```python
        # 总额硬校验：同销售合同下所有采购合同金额合计 + 本份 ≤ 销售合同额（同侧口径）
        from sqlalchemy import func
        cap = _incl_amount(parent)
        if cap is not None:
            siblings = db.execute(
                select(func.coalesce(func.sum(Contract.amount_incl_tax), 0))
                .where(Contract.parent_contract_id == parent.id)
            ).scalar() or Decimal("0")
            this_incl = amount_incl_tax if amount_incl_tax is not None else amount
            if siblings + this_incl > cap:
                raise BusinessError(
                    "AMOUNT_EXCEEDED",
                    f"超过销售合同额度：已用 {siblings} + 本份 {this_incl} > 销售额 {cap}",
                    400,
                )
```

> 说明：`select`/`func` 已 import（文件顶部 `from sqlalchemy import select`；`func` 需在 import 行补 `from sqlalchemy import func` 或函数内 import——计划采用函数内 `from sqlalchemy import func`，避免改顶部）。`Decimal` 需 import：文件顶部加 `from decimal import Decimal`。若 siblings 求和返回非 Decimal（如 float），比较前转 `Decimal(str(...))`——实现者按实际类型微调，以测试通过为准。

- [ ] **Step 4: 运行确认通过**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git -C E:\1target\SIEGPU add backend/app/services/contract_service.py backend/app/tests/test_contract_reference.py
git -C E:\1target\SIEGPU commit -m "feat(backend): 采购总额(含税)≤销售额硬校验，超限禁存"
```

---

## Task 3: 后端——销售变更返回参照计数（复核提示数据源）

**Files:**
- Modify: `backend/app/services/contract_service.py`（update_contract 检测金额变更）
- Modify: `backend/app/schemas/contract.py`（ContractOut 加 `referenced_purchase_count`）
- Test: `backend/app/tests/test_contract_reference.py`（追加）

- [ ] **Step 1: 追加失败测试**

Append to `backend/app/tests/test_contract_reference.py`:

```python
def test_update_sales_returns_reference_count(db):
    proj = _proj(db); cust, sup = _party(db)
    sales = _sales(db, proj, cust, incl=Decimal("1000"))
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("100"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("110"), parent_contract_id=sales.id)
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("200"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("220"), parent_contract_id=sales.id)
    updated = svc.update_contract(db, sales.id, amount_incl_tax=Decimal("1500"))
    assert getattr(updated, "referenced_purchase_count", None) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: 新用例 FAIL（update_contract 不返回该属性）

- [ ] **Step 3: 实现参照计数**

Modify `backend/app/services/contract_service.py` 的 `update_contract`（在 `db.flush()` 之后、return 之前）：

```python
    # 销售合同金额/条款变更后：提示其下被参照的采购合同数（前端据此提示复核）
    if c.type == "SALES":
        from sqlalchemy import func
        cnt = db.execute(
            select(func.count(Contract.id)).where(Contract.parent_contract_id == c.id)
        ).scalar() or 0
        c.referenced_purchase_count = cnt  # 非持久化属性，仅本次响应携带
```

Modify `backend/app/schemas/contract.py` 的 `ContractOut`（在 `lease_months` 字段后、`model_config` 前）：

```python
    referenced_purchase_count: int | None = None
```

> 说明：`referenced_purchase_count` 是运行时挂到 ORM 对象上的瞬态属性，Pydantic `from_attributes` 会读到它；未经过 update 的合同该字段为 None。`ContractUpdate` schema 不含 `parent_contract_id`（参照创建后锁定），无需改动。

- [ ] **Step 4: 运行确认通过**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
git -C E:\1target\SIEGPU add backend/app/services/contract_service.py backend/app/schemas/contract.py backend/app/tests/test_contract_reference.py
git -C E:\1target\SIEGPU commit -m "feat(backend): 销售合同变更返回被参照采购合同数（复核提示数据源）"
```

---

## Task 4: 后端——workflow steps 附实体 id（问题 A 数据源）

**Files:**
- Modify: `backend/app/services/workflow_service.py`（get_workflow 返回前补实体 id）
- Test: `backend/app/tests/test_workflow_step_refs.py`

- [ ] **Step 1: 读现状**

读 `backend/app/services/workflow_service.py` 的 `get_workflow`（约 97 行）与 `infer_workflow`，确认 `ProjectWorkflowOut.steps` 的 dict 结构（seq/name/status/doer_role/drawer_schema）是在哪组装返回的，找到最合适的"返回前补实体 id"的位置（get_workflow 或 API 端点 `workflows.py` 的 `get_project_workflow`）。

- [ ] **Step 2: 写失败测试**

Create `backend/app/tests/test_workflow_step_refs.py`:

```python
"""workflow steps 附带对应实体 id（步骤导航跳转用）。"""
import uuid
from decimal import Decimal

from app.models.master import Customer, Supplier
from app.models.project import Project
from app.services import contract_service as con_svc
from app.services import workflow_service as wf_svc


def test_steps_carry_entity_ids(db):
    p = Project(name=f"p{uuid.uuid4().hex[:6]}", status="进行中")
    db.add(p); db.flush()
    wf_svc.create_workflow(db, project_id=p.id)
    cust = Customer(name=f"c{uuid.uuid4().hex[:6]}")
    sup = Supplier(name=f"s{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add_all([cust, sup]); db.flush()
    sales = con_svc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"), amount_incl_tax=Decimal("1000"))
    wf = wf_svc.get_workflow(db, p.id)
    steps = {s["seq"]: s for s in wf.steps}
    assert steps[2].get("sales_contract_id") == str(sales.id)
```

- [ ] **Step 3: 运行确认失败**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_workflow_step_refs.py -x -q`
Expected: FAIL（steps 无 sales_contract_id）

- [ ] **Step 4: 实现实体 id 附加**

Modify `backend/app/services/workflow_service.py`。在 `get_workflow` 返回前（拿到 `wf` 后），按 project 查实体并给 steps 补 id：

```python
def get_workflow(db: Session, project_id: uuid.UUID) -> ProjectWorkflow | None:
    # ... 现有逻辑拿到 wf ...
    if wf is None:
        return None
    _attach_step_entity_refs(db, wf)
    return wf


def _attach_step_entity_refs(db: Session, wf: ProjectWorkflow) -> None:
    """为可跳转步骤补对应实体 id（单实体给 id + 数量；步骤导航用）。"""
    from app.models.project import Contract
    from app.models.delivery import Order
    from sqlalchemy import select
    pid = wf.project_id
    def first_of(model, **where):
        q = select(model).where(model.project_id == pid)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return db.execute(q.order_by(model.created_at.asc())).scalars().all()
    sales = first_of(Contract, type="SALES")
    purchases = first_of(Contract, type="PURCHASE")
    orders = first_of(Order)
    for s in wf.steps:
        seq = s.get("seq")
        if seq == 2 and sales:
            s["sales_contract_id"] = str(sales[0].id)
            s["sales_contract_count"] = len(sales)
        elif seq == 3 and purchases:
            s["purchase_contract_id"] = str(purchases[0].id)
            s["purchase_contract_count"] = len(purchases)
        elif seq == 4 and orders:
            s["order_id"] = str(orders[0].id)
            s["order_count"] = len(orders)
```

> 说明：实现者按 `get_workflow` 实际结构插入 `_attach_step_entity_refs` 调用（若 steps 在端点组装则在 `workflows.py` 的 `get_project_workflow` 调用）。`Contract`/`Order` 的 import 放函数内避免循环依赖。seq 2=销售合同、3=采购合同、4=批次订单，与 roleGuide.ts 的映射一致；不同模板的 seq 若不同，按步骤 `name` 匹配兜底（实现时以实际模板为准，测试用例对应标准模板）。

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run:
```
cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_workflow_step_refs.py app/tests/test_workflow_service.py -x -q
```
Expected: PASS（新 1 + 工作流回归全过）

- [ ] **Step 6: Commit**

```bash
git -C E:\1target\SIEGPU add backend/app/services/workflow_service.py backend/app/tests/test_workflow_step_refs.py
git -C E:\1target\SIEGPU commit -m "feat(backend): workflow steps 附带销售/采购/订单实体 id（步骤导航数据源）"
```

---

## Task 5: 前端——WorkflowProgress 步骤可点击 + 实体级跳转

**Files:**
- Modify: `frontend/src/components/WorkflowProgress.vue`（n-step 点击跳转）
- 参考: `frontend/src/utils/roleGuide.ts`（步骤→路由映射，复用）

- [ ] **Step 1: 实现可点击步骤**

Modify `frontend/src/components/WorkflowProgress.vue`：

```vue
<script setup lang="ts">
/**
 * 流程进度条：详情抽屉顶部展示项目流程当前进展，步骤可点击跳转对应实体。
 * 数据源：GET /workflows/{project_id} → { steps(含实体 id), current_step, status }。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NSpin, NStep, NSteps } from 'naive-ui'
import { api } from '../api/client'
import { roleName } from '../utils/role'

const props = defineProps<{ projectId: string }>()
const router = useRouter()
const wf = ref<any>(null)
const loading = ref(false)

async function load() {
  if (!props.projectId) return
  loading.value = true
  try {
    const { data } = await api.get(`/workflows/${props.projectId}`)
    wf.value = data
  } catch { wf.value = null }
  finally { loading.value = false }
}
onMounted(load)
watch(() => props.projectId, load)

const steps = computed<any[]>(() => wf.value?.steps || [])
const currentStep = computed(() => steps.value.find((s: any) => s.seq === wf.value?.current_step))

function stepStatus(s: any): 'process' | 'finish' | 'wait' | 'error' {
  if (s.status === 'done') return 'finish'
  if (s.seq === wf.value?.current_step) return 'process'
  return 'wait'
}

// 步骤→跳转目标：有实体 id 直达详情（query.detail 打开详情抽屉），多实体跳过滤列表。
function stepTarget(s: any): string | null {
  const pid = props.projectId
  switch (s.seq) {
    case 1: return `/master/projects?detail=${pid}`
    case 2:
      return s.sales_contract_count === 1
        ? `/master/contracts?detail=${s.sales_contract_id}`
        : (s.sales_contract_count ? `/master/contracts?project=${pid}&type=SALES` : null)
    case 3:
      return s.purchase_contract_count === 1
        ? `/master/contracts?detail=${s.purchase_contract_id}`
        : (s.purchase_contract_count ? `/master/contracts?project=${pid}&type=PURCHASE` : null)
    case 4:
      return s.order_count === 1
        ? `/orders?detail=${s.order_id}`
        : (s.order_count ? `/orders?project=${pid}` : null)
    case 5: case 6: case 7: return `/devices?project=${pid}`
    default: return null
  }
}

function goStep(s: any) {
  const t = stepTarget(s)
  if (t) router.push(t)
}
</script>

<template>
  <div class="wf-progress">
    <n-spin v-if="loading" size="small" />
    <template v-else-if="wf">
      <n-steps size="small">
        <n-step
          v-for="s in steps" :key="s.seq"
          :status="stepStatus(s)"
          :title="`Step ${s.seq}`"
          :description="s.name"
          :class="{ 'wf-step-clickable': !!stepTarget(s) }"
          @click="goStep(s)"
        />
      </n-steps>
      <div v-if="currentStep" class="wf-tip">
        当前进行：<strong>Step {{ currentStep.seq }} {{ currentStep.name }}</strong>
        <span v-if="currentStep.doer_role"> · 待 {{ roleName(currentStep.doer_role) }} 处理</span>
      </div>
      <div v-else-if="wf.status === 'done'" class="wf-tip">流程已全部完成</div>
    </template>
    <div v-else class="muted tiny">无流程信息</div>
  </div>
</template>

<style scoped>
.wf-progress { padding: 2px 0 6px; }
.wf-tip { margin-top: 10px; font-size: 12px; color: #64748B; }
.wf-step-clickable { cursor: pointer; }
.wf-step-clickable:hover :deep(.n-step-content__title) { color: var(--c-primary, #2563EB); text-decoration: underline; }
</style>
```

- [ ] **Step 2: 类型检查 + 构建**

Run: `cd E:\1target\SIEGPU\frontend && npx vue-tsc --noEmit 2>&1 | head -20`
Expected: 无新增类型错误（若有与本次无关的历史错误，忽略）

- [ ] **Step 3: Commit**

```bash
git -C E:\1target\SIEGPU add frontend/src/components/WorkflowProgress.vue
git -C E:\1target\SIEGPU commit -m "feat(frontend): 工作流步骤可点击并实体级跳转（详情/列表）"
```

---

## Task 6: 前端——详情抽屉支持 `?detail=<id>` 打开指定实体

**Files:**
- Modify: `frontend/src/components/GenericCrud.vue`（监听路由 query.detail 打开对应行详情）

- [ ] **Step 1: 实现 query.detail 监听**

Modify `frontend/src/components/GenericCrud.vue`。在 setup 顶部（`const showDetail = ref(false)` 附近）加入：

```ts
import { useRoute } from 'vue-router'
// ... 现有 import ...

const route = useRoute()

// 路由 query.detail=<id>：打开对应行的详情抽屉（步骤导航跳转落地用）
watch(() => route.query.detail, async (id) => {
  if (!id) return
  const row = (rows.value || []).find((r: any) => String(r.id) === String(id))
  if (row) openDetail(row)
}, { immediate: true })
```

> 说明：`openDetail` 是该组件现有的打开详情抽屉方法（实现者核对其实际名称，若叫别的如 `showDetailRow` 则用之）。`rows` 是列表数据。若路由跳转时列表尚未加载，需在 `rows` 加载完成后再匹配——实现者加一个对 `rows` 的 watch 兜底（pending detail id）。

- [ ] **Step 2: 类型检查 + Commit**

Run: `cd E:\1target\SIEGPU\frontend && npx vue-tsc --noEmit 2>&1 | head -20`

```bash
git -C E:\1target\SIEGPU add frontend/src/components/GenericCrud.vue
git -C E:\1target\SIEGPU commit -m "feat(frontend): 详情抽屉支持 ?detail=<id> 打开指定实体"
```

---

## Task 7: 前端——合同表单"参照销售合同"动态下拉（强制参照）

**Files:**
- Modify: `frontend/src/components/GenericCrud.vue`（remoteOptions 支持依赖 project_id 动态加载）
- Modify: `frontend/src/config/modules.ts`（contracts.fields 加 parent_contract_id 字段，仅 PURCHASE 显示）

- [ ] **Step 1: 实现依赖式远程下拉**

Modify `frontend/src/components/GenericCrud.vue`：给 `remoteOptions` 增加可选 `dependsOn` 机制——当依赖字段（project_id）变化时，重新拉取候选并追加过滤参数。在 `loadRemoteOptions` 基础上，为带 `remoteOptions.dependsOn` 的字段单独处理：

```ts
// 依赖式远程下拉：选项随 dependsOn 字段（如 project_id）变化重新拉取
watch(() => props.config.fields.map((f) => (f.remoteOptions?.dependsOn ? form[f.remoteOptions.dependsOn] : null)), async () => {
  for (const f of props.config.fields) {
    const ro = f.remoteOptions as any
    if (!ro?.dependsOn) continue
    const depVal = form[ro.dependsOn]
    if (!depVal) { remoteOpts[f.key] = []; continue }
    const url = `${ro.endpoint}${ro.endpoint.includes('?') ? '&' : '?'}${ro.dependsOn}=${depVal}${ro.extraQuery || ''}`
    try {
      const r = await api.get(url)
      remoteOpts[f.key] = (r.data.items || r.data || []).map((it: any) => ({ label: it[ro.label], value: it[ro.value] }))
    } catch { remoteOpts[f.key] = [] }
  }
}, { deep: true, immediate: true })
```

- [ ] **Step 2: 配置参照字段**

Modify `frontend/src/config/modules.ts` 的 `contracts.fields`（在 `party_id` 字段后插入）：

```ts
      { key: 'parent_contract_id', label: '参照销售合同', type: 'select', required: true,
        showWhen: (form: any) => form.type === 'PURCHASE',
        hint: '本采购合同参照的销售合同（必选，创建后不可改）；采购总额不得超过该销售合同额',
        remoteOptions: { endpoint: '/contracts?type=SALES', label: 'contract_no', value: 'id', dependsOn: 'project_id' } },
```

> 说明：候选 = 同 project 的 SALES 合同。后端 `/contracts?project_id=&type=` 已支持（svc.list_contracts），`dependsOn: 'project_id'` 让选项随所选项目过滤。`required: true` 前端提示，后端 create_contract 强制校验（Task 1）兜底。该字段不在 ContractUpdate schema，编辑时后端忽略（创建后锁定）；前端编辑表单如需隐藏可加 editShowWhen——实现者按现有 showWhen/editShowWhen 机制处理。

- [ ] **Step 3: 类型检查 + Commit**

Run: `cd E:\1target\SIEGPU\frontend && npx vue-tsc --noEmit 2>&1 | head -20`

```bash
git -C E:\1target\SIEGPU add frontend/src/components/GenericCrud.vue frontend/src/config/modules.ts
git -C E:\1target\SIEGPU commit -m "feat(frontend): 采购合同表单加参照销售合同动态下拉（按项目过滤，必选）"
```

---

## Task 8: 前端——详情抽屉展示参照/被参照关系

**Files:**
- Modify: `frontend/src/components/GenericCrud.vue`（合同详情：采购显示参照合同链接；销售显示被参照采购列表）
- Modify: `frontend/src/config/modules.ts`（contracts 加"被参照采购合同" detailTab）

- [ ] **Step 1: 销售合同详情加"被参照采购合同"子表**

Modify `frontend/src/config/modules.ts` 的 `contracts.detailTabs`（在"发票"之前插入）：

```ts
      { label: '被参照采购合同', endpoint: '/contracts', paramKey: 'parent_contract_id',
        columns: ['contract_no', 'amount_incl_tax', 'status'],
        labels: { contract_no: '合同号', amount_incl_tax: '金额(含税)', status: '状态' } },
```

> 说明：`detailTabs` 现有机制是 `endpoint + paramKey`（按当前行 id 查询）。后端 `list_contracts` 需支持 `parent_contract_id` 过滤参数——见 Task 9（若已支持则复用）。

- [ ] **Step 2: 采购合同详情显示参照合同链接**

Modify `frontend/src/components/GenericCrud.vue` 详情抽屉（在 `n-descriptions` 之后、`fileUpload` 之前）：

```vue
        <!-- 采购合同：参照的销售合同（可点跳转） -->
        <div v-if="detailRow?.parent_contract_id" style="margin-top:12px">
          <div class="muted tiny">参照销售合同</div>
          <n-button text type="primary" @click="goContract(detailRow.parent_contract_id)">
            {{ detailRow.parent_contract_no || detailRow.parent_contract_id }}
          </n-button>
        </div>
```

并在 setup 加：

```ts
function goContract(id: string) {
  router.push({ path: '/master/contracts', query: { detail: id } })
}
```

> 说明：`router` 需 import useRouter（Task 6 已引入 useRoute，这里补 useRouter）。`parent_contract_no` 由后端 ContractOut 提供（见 Task 9）；若无则用 id。

- [ ] **Step 3: 类型检查 + Commit**

Run: `cd E:\1target\SIEGPU\frontend && npx vue-tsc --noEmit 2>&1 | head -20`

```bash
git -C E:\1target\SIEGPU add frontend/src/components/GenericCrud.vue frontend/src/config/modules.ts
git -C E:\1target\SIEGPU commit -m "feat(frontend): 合同详情展示参照/被参照关系（可点跳转）"
```

---

## Task 9: 后端——合同查询支持 parent 过滤 + parent_contract_no 字段

**Files:**
- Modify: `backend/app/services/contract_service.py`（list_contracts 支持 parent_contract_id 过滤）
- Modify: `backend/app/schemas/contract.py`（ContractOut 加 `parent_contract_no`）
- Modify: `backend/app/api/v1/endpoints/contracts.py`（list 端点透传 parent 过滤）
- Test: `backend/app/tests/test_contract_reference.py`（追加）

- [ ] **Step 1: 追加失败测试**

Append to `backend/app/tests/test_contract_reference.py`:

```python
def test_list_by_parent_and_parent_no(db):
    proj = _proj(db); cust, sup = _party(db)
    sales = svc.create_contract(db, project_id=proj.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("1000"), contract_no="S-1")
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("100"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("110"), parent_contract_id=sales.id)
    children = svc.list_contracts(db, parent_contract_id=sales.id)
    assert len(children) == 1
    assert getattr(children[0], "parent_contract_no", None) == "S-1"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: FAIL（list_contracts 无 parent_contract_id 参数）

- [ ] **Step 3: 实现**

Modify `backend/app/services/contract_service.py` 的 `list_contracts`：

```python
def list_contracts(db: Session, project_id=None, type=None, parent_contract_id=None):
    stmt = select(Contract).order_by(Contract.created_at.desc())
    if project_id:
        stmt = stmt.where(Contract.project_id == project_id)
    if type:
        stmt = stmt.where(Contract.type == type)
    if parent_contract_id:
        stmt = stmt.where(Contract.parent_contract_id == parent_contract_id)
    rows = db.execute(stmt).scalars().all()
    # 附加 parent_contract_no（展示用瞬态属性）
    parent_ids = {r.parent_contract_id for r in rows if r.parent_contract_id}
    if parent_ids:
        parents = {p.id: p for p in db.execute(select(Contract).where(Contract.id.in_(parent_ids))).scalars().all()}
        for r in rows:
            r.parent_contract_no = parents.get(r.parent_contract_id).contract_no if r.parent_contract_id in parents else None
    return rows
```

Modify `backend/app/schemas/contract.py` 的 `ContractOut`（`parent_contract_id` 字段后）：

```python
    parent_contract_no: str | None = None
```

Modify `backend/app/api/v1/endpoints/contracts.py` 的 `list_contracts` 端点签名，加 `parent_contract_id: UUID | None = None` 查询参数并透传 `svc.list_contracts(db, ..., parent_contract_id=parent_contract_id)`。

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/test_contract_reference.py -x -q`
Expected: PASS（6 tests）

- [ ] **Step 5: Commit**

```bash
git -C E:\1target\SIEGPU add backend/app/services/contract_service.py backend/app/schemas/contract.py backend/app/api/v1/endpoints/contracts.py backend/app/tests/test_contract_reference.py
git -C E:\1target\SIEGPU commit -m "feat(backend): 合同查询支持 parent 过滤 + parent_contract_no 字段"
```

---

## Task 10: 全量回归 + 人工验收

**Files:** 无新增（验证）

- [ ] **Step 1: 后端全量回归**

Run: `cd E:\1target\SIEGPU\backend && python -m pytest app/tests/ -q 2>&1 | tail -20`
Expected: 全过（新增 6 + 既有回归；若有个别与本次无关的历史失败，记录并确认非本次引入）

- [ ] **Step 2: 前端构建**

Run: `cd E:\1target\SIEGPU\frontend && npm run build 2>&1 | tail -10`
Expected: 构建成功

- [ ] **Step 3: 人工验收清单**（重启 backend/frontend 后）

问题 B（采购参照）：
- [ ] 新建采购合同：不选销售合同被拦（前端提示 + 后端 400"必须选择参照的销售合同"）
- [ ] 选了销售合同，采购总额超过销售额被拦（提示已用/剩余额度）
- [ ] 同销售合同下建多份采购合同，合计≤销售额时可正常保存
- [ ] 编辑采购合同时无"参照销售合同"字段可改（创建后锁定）
- [ ] 销售合同改金额后，详情/提示显示"被 N 份采购合同参照，请复核"
- [ ] 采购合同详情点"参照销售合同"跳到销售合同详情；销售合同详情"被参照采购合同"列表可点

问题 A（步骤导航）：
- [ ] 订单详情顶部步骤可点击，点"销售合同"直达该项目销售合同详情
- [ ] 点"采购合同"直达采购合同详情；点"批次订单"到订单；点"设备导入"到设备列表（按项目过滤）
- [ ] 单实体直达详情、多实体跳过滤列表、无实体步骤置灰

- [ ] **Step 4: Commit 收尾**（若有验收期微调）

```bash
git -C E:\1target\SIEGPU add -A backend frontend
git -C E:\1target\SIEGPU commit -m "chore: 步骤导航+采购参照 全量验收收尾"
```

---

## 自审记录（writing-plans 要求）

- **Spec 覆盖**：设计 §3（步骤导航后端实体 id + 前端可点 + detail 打开 + 列表过滤）→ Task 4,5,6,9；§4.2 规则1 强制参照 → Task 1,7；规则2 总额校验 → Task 2；规则3 变更复核 → Task 3；§4.3 展示（参照链接/被参照列表）→ Task 8,9；§6 错误处理 → 各任务错误码与前端提示；§7 测试 → 各 Task TDD + Task 10 回归/验收。
- **占位符扫描**：无 TBD/TODO。Task 4 的"seq 若不同按 name 匹配兜底"和 Task 6 的"openDetail 名称核对"是给实现者的明确核对指令（基于现有代码的已知变体点），非占位符。
- **类型一致性**：`parent_contract_id`/`parent_contract_no`/`referenced_purchase_count`/`sales_contract_id`/`purchase_contract_id`/`order_id`/`amount_incl_tax` 前后端字段名全程一致；`_incl_amount`（Task 2）与 `_attach_step_entity_refs`（Task 4）定义处与使用处一致；`remoteOptions.dependsOn`（Task 7）在 GenericCrud 的监听逻辑里同名。
