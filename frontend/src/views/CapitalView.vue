<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NFormItem, NInput, NInputNumber, NSelect, NSpace, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import * as R from '../composables/useResource'
import { money } from '../utils/format'
import EChart from '../components/EChart.vue'

const msg = useMessage()
const summary = ref<any>({ pool_balance: 0, total_in: 0, total_out: 0, by_source: {}, per_project: [] })
const txns = ref<any[]>([])
const projects = ref<any[]>([])

const form = reactive({
  project_id: '' as string, source_type: '自有资金', direction: 'IN',
  amount: null as number | null, transaction_date: '', note: '',
})
const SOURCE_OPTS = ['自有资金', '银行流贷', '金租融资', '租金收入', '还款'].map((v) => ({ label: v, value: v }))
const DIR_OPTS = [{ label: '入金 IN', value: 'IN' }, { label: '出金 OUT', value: 'OUT' }]

async function refresh() {
  try {
    const [s, t, p] = await Promise.all([api.get('/capital/summary'), api.get('/capital/transactions'), api.get('/projects')])
    summary.value = s.data; txns.value = t.data.items; projects.value = p.data.items
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

async function submit() {
  if (!form.project_id || !form.amount || !form.transaction_date) { msg.warning('请填齐 项目/金额/日期'); return }
  try {
    await R.createRes('/capital/transactions', { ...form })
    msg.success('已记账'); await refresh()
    form.amount = null; form.note = ''
  } catch (e: any) { msg.error(e.response?.data?.detail?.message || '记账失败') }
}

const pieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, type: 'scroll' },
  series: [{
    type: 'pie', radius: ['42%', '68%'], center: ['50%', '44%'],
    avoidLabelOverlap: true, padAngle: 2,
    label: { show: true, formatter: '{b}\n{d}%', fontSize: 11 },
    data: Object.entries(summary.value.by_source || {}).map(([k, v]: [string, any]) => ({ name: k, value: Number(v.in) })),
  }],
}))

const txnCols = [
  { title: '日期', key: 'transaction_date', width: 110 },
  { title: '来源', key: 'source_type', width: 100 },
  { title: '方向', key: 'direction', width: 70 },
  { title: '金额', key: 'amount', align: 'right', className: 'num', render: (r: any) => money(r.amount) },
  { title: '摘要', key: 'note' },
]
</script>

<template>
  <div>
    <n-space :size="16">
      <n-card class="kpi"><div class="kpi-label">资金池余额</div><div class="kpi-val num">{{ money(summary.pool_balance) }}</div></n-card>
      <n-card class="kpi"><div class="kpi-label">累计入金</div><div class="kpi-val num in">{{ money(summary.total_in) }}</div></n-card>
      <n-card class="kpi"><div class="kpi-label">累计出金</div><div class="kpi-val num out">{{ money(summary.total_out) }}</div></n-card>
    </n-space>

    <div class="grid">
      <n-card title="记一笔">
        <n-space wrap :size="12">
          <n-form-item label="项目" :show-feedback="false">
            <n-select v-model:value="form.project_id" :options="projects.map((p:any)=>({label:p.name,value:p.id}))" style="width:180px" placeholder="选项目" />
          </n-form-item>
          <n-form-item label="来源" :show-feedback="false">
            <n-select v-model:value="form.source_type" :options="SOURCE_OPTS" style="width:130px" />
          </n-form-item>
          <n-form-item label="方向" :show-feedback="false">
            <n-select v-model:value="form.direction" :options="DIR_OPTS" style="width:110px" />
          </n-form-item>
          <n-form-item label="金额" :show-feedback="false">
            <n-input-number v-model:value="form.amount" style="width:150px" :show-button="false" placeholder="金额" />
          </n-form-item>
          <n-form-item label="日期" :show-feedback="false">
            <n-input v-model:value="form.transaction_date" placeholder="YYYY-MM-DD" style="width:140px" />
          </n-form-item>
          <n-form-item label="摘要" :show-feedback="false">
            <n-input v-model:value="form.note" placeholder="可选" style="width:160px" />
          </n-form-item>
          <n-button type="primary" @click="submit">记一笔</n-button>
        </n-space>
      </n-card>
      <n-card title="收入构成（按来源）">
        <EChart :option="pieOption" height="240px" />
      </n-card>
    </div>

    <n-card title="资金流水" style="margin-top:16px">
      <n-data-table :columns="txnCols" :data="txns" :bordered="false" size="small" striped :pagination="{ pageSize: 12 }" />
    </n-card>
  </div>
</template>

<style scoped>
.kpi { flex: 1; min-width: 180px; }
.kpi-label { font-size: 12px; color: var(--c-text-2); }
.kpi-val { font-size: 24px; font-weight: 700; margin-top: 6px; }
.kpi-val.in { color: var(--c-success); }
.kpi-val.out { color: var(--c-warning); }
.grid { display: grid; grid-template-columns: 1.6fr 1fr; gap: 16px; margin-top: 16px; }
@media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
