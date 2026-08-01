<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NIcon, NSpace, NStatistic, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { AlertTriangle, Wallet } from 'lucide-vue-next'
import { api } from '../api/client'
import { money } from '../utils/format'
import { roleName } from '../utils/role'
import EChart from '../components/EChart.vue'

const msg = useMessage()
const summary = ref<any>({})
const alerts = ref<any[]>([])
const overview = ref<any[]>([])
const months = ref<any[]>([])

const myTasks = ref<any[]>([])

async function refresh() {
  try {
    const [s, a, o, m, t] = await Promise.all([
      api.get('/capital/summary'), api.get('/dashboard/alerts'),
      api.get('/reports/project-overview'), api.get('/reports/capital-monthly'),
      api.get('/workflows/my-tasks'),
    ])
    summary.value = s.data
    alerts.value = a.data.items
    overview.value = o.data.items
    months.value = (m.data.items || []).slice(-12)
    myTasks.value = t.data || []
  } catch { msg.error('加载失败') }
}

// 30 秒静默轮询待办：只更新 myTasks，不触发整页 loading、失败不打扰用户
async function pollTasks() {
  try {
    const t = await api.get('/workflows/my-tasks')
    myTasks.value = t.data || []
  } catch { /* 静默轮询失败不提示 */ }
}

let pollTimer: number | undefined
onMounted(() => {
  refresh()
  pollTimer = window.setInterval(pollTasks, 30000)
})
onUnmounted(() => { if (pollTimer !== undefined) window.clearInterval(pollTimer) })

// 全新部署：无待办且总览为空（KPI 全空）→ 显示新手引导
const isFresh = computed(() =>
  !myTasks.value.length && !overview.value.length && !alerts.value.length && !summary.value.pool_balance,
)
const hasTasks = computed(() => myTasks.value.length > 0)

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
const ovCols: DataTableColumns = [
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

    <!-- v3.2 待办任务 -->
    <n-card v-if="hasTasks" title="待处理" style="margin-top:16px">
      <div v-for="t in myTasks" :key="t.project_id + '-' + t.step_seq"
        style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #F1F5F9">
        <div>
          <span style="font-weight:600">{{ t.project_name }}</span>
          <span style="color:#64748B;margin-left:8px">Step {{ t.step_seq }} — {{ t.step_name }}</span>
          <n-tag size="tiny" style="margin-left:8px">{{ roleName(t.doer_role) }}</n-tag>
        </div>
        <router-link :to="'/projects/' + t.project_id + '/workspace'">
          <n-button size="small" type="primary">立即处理</n-button>
        </router-link>
      </div>
    </n-card>

    <!-- 全新部署：新手引导 -->
    <n-card v-else-if="isFresh" title="欢迎使用 SIEGPU ERP" style="margin-top:16px">
      <div style="color:#64748B;font-size:13px;line-height:2">
        <div>
          ① 先建主数据：
          <router-link to="/master/suppliers">供应商</router-link> ·
          <router-link to="/master/customers">客户</router-link> ·
          <router-link to="/master/equipment">设备型号</router-link> ·
          <router-link to="/master/banks">银行</router-link>
        </div>
        <div>
          ② <router-link to="/master/projects">创建项目</router-link>，系统将自动生成向导式工作流程
        </div>
        <div>
          ③ 想快速体验？载入演示数据：<code>docker compose exec backend python -m app.demo</code>
        </div>
      </div>
    </n-card>

    <!-- 有数据但无待办 -->
    <n-card v-else size="small" style="margin-top:16px">
      <span style="color:#64748B">暂无待办，一切就绪</span>
    </n-card>

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
