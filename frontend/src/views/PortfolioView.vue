<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NDataTable, NInput, NProgress, NSelect, NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api } from '../api/client'
import { money, statusTagType } from '../utils/format'
import { roleName } from '../utils/role'
import EmptyState from '../components/EmptyState.vue'

const msg = useMessage()
const router = useRouter()
const items = ref<any[]>([])

// 筛选：项目名搜索 + 状态过滤（'' = 全部）
const search = ref('')
const statusFilter = ref('')

async function refresh() {
  try {
    const { data } = await api.get('/workflows/portfolio')
    items.value = data.items || []
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

function progressPct(r: any): number {
  if (!r.total_steps) return 0
  return Math.round((r.done_count / r.total_steps) * 100)
}

// 停滞天数：>7 天标黄，>14 天标红
function stagnationTag(r: any) {
  const d = Number(r.stagnation_days || 0)
  const type = d > 14 ? 'error' : d > 7 ? 'warning' : 'default'
  return h(NTag, { size: 'small', bordered: false, type }, () => `${d} 天`)
}

// —— 筛选后的行 ——
const filtered = computed(() => items.value.filter((r: any) => {
  if (statusFilter.value && r.status !== statusFilter.value) return false
  if (search.value && !String(r.project_name).toLowerCase().includes(search.value.trim().toLowerCase())) return false
  return true
}))

// 状态选项从数据动态提取（去重）
const statusOpts = computed(() => {
  const ss = [...new Set(items.value.map((r: any) => r.status).filter(Boolean))] as string[]
  return [{ label: '全部状态', value: '' }, ...ss.map((s) => ({ label: s, value: s }))]
})

// —— KPI 行（基于全量，不随筛选变化） ——
const kpi = computed(() => ({
  total: items.value.length,
  active: items.value.filter((r: any) => r.status === '进行中').length,
  stagnant: items.value.filter((r: any) => Number(r.stagnation_days || 0) > 7).length,
  salesTotal: items.value.reduce((s: number, r: any) => s + Number(r.sales_total || 0), 0),
}))

const cols: DataTableColumns = [
  { title: '项目', key: 'project_name', render: (r: any) => h('span', { style: 'font-weight:600' }, r.project_name) },
  { title: '当前步骤', key: 'current_step_name', render: (r: any) =>
      r.current_step_name ? `Step ${r.current_step} — ${r.current_step_name}` : '—' },
  { title: '进度', key: '__progress', width: 150, render: (r: any) =>
      h('div', { style: 'display:flex;align-items:center;gap:8px' }, [
        h(NProgress, { type: 'line', percentage: progressPct(r), showIndicator: false, style: 'flex:1' }),
        h('span', { class: 'num', style: 'font-size:12px;color:#64748B' }, `${progressPct(r)}%`),
      ]) },
  { title: '销售合同额', key: 'sales_total', width: 130, align: 'right', className: 'num',
    render: (r: any) => money(r.sales_total) },
  { title: '金租已放款', key: 'leasing_disbursed', width: 120, align: 'right', className: 'num',
    render: (r: any) => money(r.leasing_disbursed) },
  { title: '预付余额', key: 'prepay_remaining', width: 110, align: 'right', className: 'num',
    render: (r: any) => money(r.prepay_remaining) },
  { title: '状态', key: 'status', width: 90, render: (r: any) =>
      h(NTag, { size: 'small', bordered: false, type: statusTagType(r.status) as any }, () => r.status) },
  { title: '待办角色', key: 'doer_role', width: 120, render: (r: any) => roleName(r.doer_role) },
  { title: '停滞天数', key: 'stagnation_days', width: 90, align: 'center', render: stagnationTag },
]

const rowProps = (r: any) => ({
  style: 'cursor:pointer',
  onClick: () => router.push(`/projects/${r.project_id}/workspace`),
  // e2e 锚点：按项目名定位行
  'data-project': r.project_name,
})
</script>

<template>
  <div>
    <!-- KPI 行 -->
    <div style="display:flex;gap:16px;margin-bottom:14px">
      <n-card class="kpi"><div class="kpi-label">项目总数</div><div class="kpi-val num">{{ kpi.total }}</div></n-card>
      <n-card class="kpi"><div class="kpi-label">进行中</div><div class="kpi-val num">{{ kpi.active }}</div></n-card>
      <n-card class="kpi"><div class="kpi-label">停滞 &gt;7 天</div>
        <div class="kpi-val num" :style="kpi.stagnant > 0 ? 'color:#D97706' : ''">{{ kpi.stagnant }}</div></n-card>
      <n-card class="kpi"><div class="kpi-label">销售合同总额</div><div class="kpi-val num">{{ money(kpi.salesTotal) }}</div></n-card>
    </div>

    <n-card title="项目组合总览" :bordered="false">
      <div class="muted tiny" style="margin-bottom:10px">
        各项目工作流实时状态一览；停滞 &gt;7 天标黄、&gt;14 天标红。点击行进入项目工作台（业务对象血缘树在详情页）。
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <n-input v-model:value="search" placeholder="搜索项目名…" clearable style="width:220px" data-testid="pf-search" />
        <n-select v-model:value="statusFilter" :options="statusOpts" style="width:140px" data-testid="pf-status" />
      </div>
      <n-data-table :columns="cols" :data="filtered" :bordered="false" size="small" striped :row-props="rowProps">
        <template #empty>
          <EmptyState description="还没有项目，建立第一个项目后这里会显示流程进度" cta-label="去建项目" cta-route="/master/projects" />
        </template>
      </n-data-table>
    </n-card>
  </div>
</template>

<style scoped>
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.kpi { flex: 1; min-width: 150px; }
.kpi-label { font-size: 12px; color: var(--c-text-2); }
.kpi-val { font-size: 24px; font-weight: 700; margin-top: 6px; }
</style>
