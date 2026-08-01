<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NAlert, NCard, NDataTable, NIcon, NSpace, NStatistic, useMessage } from 'naive-ui'
import { AlertTriangle, Wallet } from 'lucide-vue-next'
import { api } from '../api/client'
import { money } from '../utils/format'
import EChart from '../components/EChart.vue'

const msg = useMessage()
const summary = ref<any>({})
const alerts = ref<any[]>([])
const overview = ref<any[]>([])
const months = ref<any[]>([])

async function refresh() {
  try {
    const [s, a, o, m] = await Promise.all([
      api.get('/capital/summary'), api.get('/dashboard/alerts'),
      api.get('/reports/project-overview'), api.get('/reports/capital-monthly'),
    ])
    summary.value = s.data
    alerts.value = a.data.items
    overview.value = o.data.items
    months.value = (m.data.items || []).slice(-12)
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

const monthlyOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  legend: { data: ['入金', '出金'], top: 0, right: 0 },
  grid: { left: 4, right: 8, top: 36, bottom: 4, containLabel: true },
  xAxis: { type: 'category', data: months.value.map((m) => m.month), axisTick: { show: false } },
  yAxis: { type: 'value' },
  series: [
    { name: '入金', type: 'bar', stack: 'a', data: months.value.map((m) => Number(m.in)), itemStyle: { color: '#B45309', borderRadius: [0, 0, 4, 4] }, barWidth: 18 },
    { name: '出金', type: 'bar', data: months.value.map((m) => Number(m.out)), itemStyle: { color: '#94A3B8', borderRadius: [4, 4, 0, 0] }, barWidth: 18 },
  ],
}))

const monthlyDep = computed(() => overview.value.reduce((s, p) => s + Number(p.monthly_depreciation || 0), 0))
const ovCols = [
  { title: '项目', key: 'name' },
  { title: '净头寸', key: 'net_position', align: 'right', className: 'num', render: (r: any) => money(r.net_position) },
  { title: '金租', key: 'leasing_count', align: 'center', render: (r: any) => r.leasing_count ? `${r.leasing_count}·${r.leasing_status}` : '-' },
  { title: '资产', key: 'asset_count', align: 'center' },
  { title: '月折旧', key: 'monthly_depreciation', align: 'right', className: 'num', render: (r: any) => money(r.monthly_depreciation) },
]
</script>

<template>
  <div>
    <n-space :size="16">
      <n-card class="kpi"><n-statistic label="资金池余额"><span class="num">{{ money(summary.pool_balance) }}</span></n-statistic></n-card>
      <n-card class="kpi"><n-statistic label="项目数" :value="overview.length" /></n-card>
      <n-card class="kpi"><n-statistic label="预警" :value="alerts.length" /></n-card>
      <n-card class="kpi"><n-statistic label="月折旧合计"><span class="num">{{ money(monthlyDep) }}</span></n-statistic></n-card>
    </n-space>

    <div class="grid">
      <n-card title="资金月度趋势" class="span2">
        <EChart :option="monthlyOption" height="300px" />
      </n-card>
      <n-card title="预警">
        <n-alert v-if="!alerts.length" type="success" :bordered="false">
          <template #header>暂无预警</template>当前各项指标正常
        </n-alert>
        <n-space vertical :size="8" v-else>
          <n-alert
            v-for="(a, i) in alerts" :key="i"
            :type="a.level === '高危' ? 'error' : 'warning'"
            :title="a.code" :bordered="false"
          >
            {{ a.message }}
          </n-alert>
        </n-space>
      </n-card>
    </div>

    <n-card title="项目概览" style="margin-top:16px">
      <n-data-table :columns="ovCols" :data="overview" :bordered="false" size="small" />
    </n-card>
  </div>
</template>

<style scoped>
.kpi { flex: 1; min-width: 160px; }
.grid { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-top: 16px; }
.span2 { grid-row: span 1; }
@media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
