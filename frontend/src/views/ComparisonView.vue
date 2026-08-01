<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NCard, NDataTable, NProgress, NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api } from '../api/client'
import { money } from '../utils/format'

const msg = useMessage()
const items = ref<any[]>([])

async function refresh() {
  try {
    const { data } = await api.get('/reports/project-comparison')
    items.value = data.items || []
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

const num = (v: unknown) => (v === null || v === undefined || v === '' ? null : Number(v))
const numSorter = (key: string) => (a: any, b: any) => (num(a[key]) ?? -Infinity) - (num(b[key]) ?? -Infinity)

const cols: DataTableColumns = [
  { title: '项目', key: 'project_name', sorter: (a: any, b: any) => String(a.project_name).localeCompare(String(b.project_name), 'zh-CN'),
    render: (r: any) => h('span', { style: 'font-weight:600' }, r.project_name) },
  { title: 'IRR(年化)', key: 'irr', align: 'right', className: 'num', sorter: numSorter('irr'),
    render: (r: any) => (num(r.irr) === null ? '—' : `${money(r.irr)}%`) },
  { title: 'NPV(5%)', key: 'npv', align: 'right', className: 'num', sorter: numSorter('npv'),
    render: (r: any) => money(r.npv) },
  { title: '总利润', key: 'total_profit', align: 'right', className: 'num', sorter: numSorter('total_profit'),
    render: (r: any) => money(r.total_profit) },
  { title: '回款率', key: 'collection_rate', align: 'right', className: 'num', sorter: numSorter('collection_rate'),
    render: (r: any) => {
      const v = num(r.collection_rate)
      if (v === null) return '—'
      const color = v >= 80 ? '#16A34A' : v >= 50 ? '#D97706' : '#DC2626'
      return h('span', { style: `color:${color};font-weight:600` }, `${money(v)}%`)
    } },
  { title: '逾期笔数', key: 'overdue_count', align: 'center', width: 100, sorter: numSorter('overdue_count'),
    render: (r: any) => {
      const n = Number(r.overdue_count || 0)
      return n > 0
        ? h(NTag, { size: 'small', type: 'error', bordered: false }, () => `${n} 笔`)
        : h('span', { style: 'color:#94A3B8' }, '0')
    } },
  { title: '工作流进度', key: 'progress_pct', width: 180, sorter: numSorter('progress_pct'),
    render: (r: any) => h('div', { style: 'display:flex;align-items:center;gap:8px' }, [
      h(NProgress, { type: 'line', percentage: Number(r.progress_pct || 0), showIndicator: false, style: 'flex:1' }),
      h('span', { class: 'num', style: 'font-size:12px;color:#64748B' }, `${Number(r.progress_pct || 0)}%`),
    ]) },
]
</script>

<template>
  <div>
    <n-card title="项目对比" :bordered="false">
      <div class="muted tiny" style="margin-bottom:10px">
        各项目盈利与回款指标横向对比；点击列头可排序。回款率 = 已收款 / 应收(计费)。
      </div>
      <n-data-table :columns="cols" :data="items" :bordered="false" size="small" striped />
    </n-card>
  </div>
</template>

<style scoped>
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
