<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NFormItem, NInputNumber, NSelect, NSpace, NStatistic, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { money } from '../utils/format'
import EChart from '../components/EChart.vue'

interface MonthlyRow {
  month: number
  rent: number
  opex: number
  depreciation: number
  lease_principal: number
  lease_interest: number
  pre_tax_profit: number
  net_cashflow: number
  cumulative: number
}
interface ProfitSummary {
  equity_investment: number
  total_revenue_ex_tax: number
  total_opex: number
  total_depreciation: number
  total_lease_interest: number
  total_profit: number
  irr_annual_pct: number | null
  npv_5pct: number
  payback_month: number | null
  monthly_net_avg: number
}
interface ProfitResult {
  monthly: MonthlyRow[]
  summary: ProfitSummary
}

// IRR(年化) 高于此视为优质项目，绿色显示
const IRR_GOOD = 15

const msg = useMessage()
const projects = ref<{ id: string; name: string }[]>([])
const loading = ref(false)
const result = ref<ProfitResult | null>(null)

// 手动输入参数（默认填商机5090的真实值）
const form = ref({
  purchase_ex_tax: 734566371.68,
  purchase_incl_tax: 830060000,
  monthly_rent: 21677600,
  term_months: 60,
  annual_rate: 0.04,
  lease_term: 60,
  payment_freq: '月',
  repayment_method: '等额本息',
  depreciation_years: 5,
  residual_rate: 0.10,
  monthly_opex: 4116000,
  tax_rate: 0.06,
  equity_ratio: 0.10,
})

async function refresh() {
  try {
    const { data } = await api.get('/projects')
    projects.value = data.items
  } catch {}
}
onMounted(refresh)

async function runCalc(fn: () => Promise<ProfitResult>, failMsg: string) {
  loading.value = true
  try {
    result.value = await fn()
  } catch (e: any) { msg.error(e.response?.data?.detail?.message || failMsg) }
  finally { loading.value = false }
}

function calcManual() {
  runCalc(() => api.post('/reports/profit/calculate', form.value).then(r => r.data), '计算失败')
}
function calcProject(pid: string) {
  runCalc(() => api.get(`/reports/profit/${pid}`).then(r => r.data), '计算失败')
}

const chartOption = computed(() => {
  const monthly = result.value?.monthly || []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 12, top: 20, bottom: 4, containLabel: true },
    xAxis: { type: 'category', data: monthly.map((r) => `M${r.month}`) },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => (v / 1e8).toFixed(1) + '亿' } },
    series: [
      { name: '累计现金流', type: 'line', smooth: true, data: monthly.map((r) => r.cumulative),
        itemStyle: { color: '#B45309' }, areaStyle: { opacity: 0.08 },
        markLine: { data: [{ yAxis: 0 }], lineStyle: { color: '#DC2626', type: 'dashed' } } },
      { name: '月净现金流', type: 'bar', data: monthly.map((r) => r.net_cashflow),
        itemStyle: { color: '#94A3B8', opacity: 0.5 }, barWidth: 6 },
    ],
  }
})

const tableCols = [
  { title: '月', key: 'month', width: 50, align: 'center' },
  { title: '租金', key: 'rent', align: 'right', render: (r: MonthlyRow) => money(r.rent) },
  { title: '运营', key: 'opex', align: 'right', render: (r: MonthlyRow) => money(r.opex) },
  { title: '折旧', key: 'depreciation', align: 'right', render: (r: MonthlyRow) => money(r.depreciation) },
  { title: '还本', key: 'lease_principal', align: 'right', render: (r: MonthlyRow) => money(r.lease_principal) },
  { title: '付息', key: 'lease_interest', align: 'right', render: (r: MonthlyRow) => money(r.lease_interest) },
  { title: '税前利润', key: 'pre_tax_profit', align: 'right', render: (r: MonthlyRow) => money(r.pre_tax_profit) },
  { title: '净现金流', key: 'net_cashflow', align: 'right', render: (r: MonthlyRow) => money(r.net_cashflow) },
  { title: '累计', key: 'cumulative', align: 'right', render: (r: MonthlyRow) => money(r.cumulative) },
]

interface Kpi { label: string; value: string; color?: string; num?: boolean }
const kpis = computed<Kpi[]>(() => {
  const s = result.value?.summary
  if (!s) return []
  return [
    { label: 'IRR (年化)', value: `${s.irr_annual_pct}%`, color: (s.irr_annual_pct ?? 0) > IRR_GOOD ? '#16A34A' : '#DC2626' },
    { label: 'NPV (5%贴现)', value: money(s.npv_5pct), num: true },
    { label: '回本月', value: `${s.payback_month} 月` },
    { label: '总税前利润', value: money(s.total_profit), num: true },
    { label: '月均净现金流', value: money(s.monthly_net_avg), num: true },
    { label: '自有投入', value: money(s.equity_investment), num: true },
  ]
})
</script>

<template>
  <div>
    <div class="grid">
      <!-- 输入参数 -->
      <n-card title="测算参数">
        <n-space vertical :size="8">
          <n-form-item label="按项目自动算" :show-feedback="false">
            <n-select :options="projects.map((p) => ({ label: p.name, value: p.id }))" placeholder="选项目→自动取参数" @update:value="calcProject" style="width:100%" />
          </n-form-item>
          <div class="muted tiny" style="text-align:center">— 或手动调整参数 —</div>
          <n-space :size="8" wrap>
            <n-form-item label="采购(不含税)" :show-feedback="false"><n-input-number v-model:value="form.purchase_ex_tax" :show-button="false" style="width:140px" /></n-form-item>
            <n-form-item label="月租金(含税)" :show-feedback="false"><n-input-number v-model:value="form.monthly_rent" :show-button="false" style="width:140px" /></n-form-item>
            <n-form-item label="出租月数" :show-feedback="false"><n-input-number v-model:value="form.term_months" :show-button="false" style="width:80px" /></n-form-item>
            <n-form-item label="年利率" :show-feedback="false"><n-input-number v-model:value="form.annual_rate" :step="0.005" :show-button="false" style="width:80px" /></n-form-item>
            <n-form-item label="金租期数" :show-feedback="false"><n-input-number v-model:value="form.lease_term" :show-button="false" style="width:80px" /></n-form-item>
            <n-form-item label="月运营成本" :show-feedback="false"><n-input-number v-model:value="form.monthly_opex" :show-button="false" style="width:140px" /></n-form-item>
            <n-form-item label="自有比例" :show-feedback="false"><n-input-number v-model:value="form.equity_ratio" :step="0.05" :show-button="false" style="width:80px" /></n-form-item>
            <n-form-item label="残值率" :show-feedback="false"><n-input-number v-model:value="form.residual_rate" :step="0.05" :show-button="false" style="width:80px" /></n-form-item>
          </n-space>
          <n-button type="primary" block :loading="loading" @click="calcManual">计算利润</n-button>
        </n-space>
      </n-card>

      <!-- 结果 KPI -->
      <n-space v-if="result?.summary" :size="12">
        <n-card v-for="k in kpis" :key="k.label" class="kpi">
          <n-statistic :label="k.label">
            <span v-if="k.color" :style="{ color: k.color, fontWeight: 700 }">{{ k.value }}</span>
            <span v-else :class="{ num: k.num }">{{ k.value }}</span>
          </n-statistic>
        </n-card>
      </n-space>
    </div>

    <template v-if="result">
      <!-- 现金流图 -->
      <n-card title="累计现金流走势" style="margin-top:16px">
        <EChart :option="chartOption" height="320px" />
      </n-card>

      <!-- 月度明细 -->
      <n-card title="月度现金流明细" style="margin-top:16px">
        <n-data-table :columns="tableCols" :data="result.monthly" :bordered="false" size="small" striped
          :pagination="{ pageSize: 12 }" :max-height="400" />
      </n-card>
    </template>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: 360px 1fr; gap: 16px; align-items: start; }
.kpi { min-width: 140px; }
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>
