<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NDataTable, NProgress, NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api } from '../api/client'
import { statusTagType } from '../utils/format'
import { roleName } from '../utils/role'

const msg = useMessage()
const router = useRouter()
const items = ref<any[]>([])

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

const cols: DataTableColumns = [
  { title: '项目', key: 'project_name', render: (r: any) => h('span', { style: 'font-weight:600' }, r.project_name) },
  { title: '当前步骤', key: 'current_step_name', render: (r: any) =>
      r.current_step_name ? `Step ${r.current_step} — ${r.current_step_name}` : '—' },
  { title: '进度', key: '__progress', width: 180, render: (r: any) =>
      h('div', { style: 'display:flex;align-items:center;gap:8px' }, [
        h(NProgress, { type: 'line', percentage: progressPct(r), showIndicator: false, style: 'flex:1' }),
        h('span', { class: 'num', style: 'font-size:12px;color:#64748B' }, `${progressPct(r)}%`),
      ]) },
  { title: '状态', key: 'status', width: 90, render: (r: any) =>
      h(NTag, { size: 'small', bordered: false, type: statusTagType(r.status) as any }, () => r.status) },
  { title: '待办角色', key: 'doer_role', width: 130, render: (r: any) => roleName(r.doer_role) },
  { title: '停滞天数', key: 'stagnation_days', width: 100, align: 'center', render: stagnationTag },
]

const rowProps = (r: any) => ({
  style: 'cursor:pointer',
  onClick: () => router.push(`/projects/${r.project_id}/workspace`),
})
</script>

<template>
  <div>
    <n-card title="项目组合总览" :bordered="false">
      <div class="muted tiny" style="margin-bottom:10px">
        各项目工作流实时状态一览；停滞 &gt;7 天标黄、&gt;14 天标红。点击行进入项目工作台。
      </div>
      <n-data-table :columns="cols" :data="items" :bordered="false" size="small" striped :row-props="rowProps" />
    </n-card>
  </div>
</template>

<style scoped>
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
