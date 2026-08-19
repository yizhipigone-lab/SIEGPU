<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert, NButton, NCard, NDataTable, NIcon, NModal, NSkeleton, NSpace, NStatistic, NTag,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { ArrowRight, ListChecks, Map, X } from 'lucide-vue-next'
import { api } from '../api/client'
import { money } from '../utils/format'
import { roleName } from '../utils/role'
import { useAuthStore } from '../stores/auth'
import {
  getRoleGuide, readHideGuideBanner, seesOriginalDashboard, writeHideGuideBanner,
} from '../utils/roleGuide'
import EChart from '../components/EChart.vue'
import FlowMap from '../components/FlowMap.vue'
import OnboardingTour from '../components/OnboardingTour.vue'

const msg = useMessage()
const router = useRouter()
const auth = useAuthStore()
const summary = ref<any>({})
const alerts = ref<any[]>([])
const overview = ref<any[]>([])
const months = ref<any[]>([])
const myTasks = ref<any[]>([])
const board = ref<any>(null)  // 三期 §4.5 经营看板
const loading = ref(false)
const loadFailed = ref(false)
const loadedOnce = ref(false)

async function refresh() {
  loading.value = true
  loadFailed.value = false
  try {
    const [s, a, o, m, t, b] = await Promise.all([
      api.get('/capital/summary'), api.get('/dashboard/alerts'),
      api.get('/reports/project-overview'), api.get('/reports/capital-monthly'),
      api.get('/workflows/my-tasks'), api.get('/dashboard/business'),
    ])
    summary.value = s.data
    alerts.value = a.data.items
    overview.value = o.data.items
    months.value = (m.data.items || []).slice(-12)
    myTasks.value = t.data || []
    board.value = b.data
    loadedOnce.value = true
  } catch { loadFailed.value = true; msg.error('加载失败') }
  finally { loading.value = false }
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

// —— 角色化首页（采购/交付/财务专员）——
const useOriginal = computed(() => seesOriginalDashboard(auth.role))
const guide = computed(() => getRoleGuide(auth.role))
const hasTasks = computed(() => myTasks.value.length > 0)
const showBanner = ref(!readHideGuideBanner())
function dismissBanner() {
  showBanner.value = false
  writeHideGuideBanner(true)
}
const showFlowModal = ref(false)
const myFlowSeqs = computed(() => guide.value?.flowStepSeqs ?? [])
// 待办锚点：把「我的待办」步骤名透传给 FlowMap，对应节点打「进行中」脉冲点
const activeStepNames = computed(() => myTasks.value.map((t) => t.step_name).filter(Boolean))

// —— 一键载入演示项目（P3，仅管理员/财务总监）——
const demoLoading = ref(false)
const canLoadDemo = computed(() => auth.role === 'ADMIN' || auth.role === 'FINANCE_DIRECTOR')
async function loadDemo() {
  demoLoading.value = true
  try {
    const r = await api.post('/demo/load')
    if (r.data?.loaded) msg.success('演示项目「商机5090」已载入，正在刷新…')
    else msg.info(r.data?.message || '演示项目已存在')
    await refresh()
  } catch { msg.error('载入演示项目失败') }
  finally { demoLoading.value = false }
}

// 全新部署：无待办且总览为空（KPI 全空）→ 显示新手引导
// 原首页分支据此显示欢迎卡；角色首页分支显示「快速开始」卡
const isFresh = computed(() =>
  !myTasks.value.length && !overview.value.length && !alerts.value.length && !summary.value.pool_balance,
)
const isProcurement = computed(() => auth.role === 'PROCUREMENT')

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
    <!-- 首次登录分步引导（走完/点任意处自动关闭，localStorage 记忆）。
         仅角色化首页（采购/交付/财务）展示：管理员/总监看的是经营看板（原首页），
         且引导步骤（流程图「你负责」高亮、待办卡）是角色化概念，对管理层不适用，故默认跳过。 -->
    <onboarding-tour v-if="!useOriginal && guide" />

    <!-- 加载失败：内联重试 -->
    <n-card v-if="loadFailed" style="margin-bottom:16px" data-testid="load-failed">
      <div style="text-align:center;padding:12px">
        <div style="color:#94A3B8;margin-bottom:8px">首页加载失败，请检查网络或稍后重试</div>
        <n-button type="primary" size="small" @click="refresh">重试</n-button>
      </div>
    </n-card>

    <!-- 首次加载骨架屏 -->
    <template v-else-if="loading && !loadedOnce">
      <n-space vertical :size="16">
        <n-skeleton text :repeat="2" />
        <n-skeleton text style="width:60%" />
        <n-skeleton height="160px" />
      </n-space>
    </template>

    <!-- ===== 角色化首页（采购 / 交付 / 财务专员） ===== -->
    <template v-else-if="!useOriginal && guide">
      <!-- 角色职责横幅：新人第一眼「我是谁、负责哪几环」。文本刻意不含「待处理」，避免与待办卡 e2e 定位冲突。 -->
      <n-card v-if="showBanner" class="role-banner" :bordered="false">
        <div class="banner-row">
          <div class="banner-main">
            <div class="banner-title">
              你是 <strong>{{ guide.title }}</strong>
              <span class="banner-flow">· 整个流程里你负责 {{ guide.flowRange }}</span>
            </div>
            <div class="banner-resp">
              <n-tag
                v-for="r in guide.responsibilities" :key="r"
                size="small" round :bordered="false" type="warning"
              >{{ r }}</n-tag>
            </div>
          </div>
          <div class="banner-actions">
            <n-button size="small" @click="showFlowModal = true">
              <template #icon><n-icon><Map /></n-icon></template>
              看完整流程
            </n-button>
            <n-button size="small" quaternary aria-label="收起引导" @click="dismissBanner">
              <template #icon><n-icon><X /></n-icon></template>
            </n-button>
          </div>
        </div>
      </n-card>

      <!-- 业务流程图：点击节点直达对应页面，本角色负责的环节高亮 -->
      <n-card style="margin-top:16px" data-testid="flow-map">
        <template #header>
          <span>业务流程图 <span class="tiny" style="color:#94A3B8;font-weight:400">点击节点直达对应页面，高亮的是你负责的环节</span></span>
        </template>
        <FlowMap :highlight-seqs="myFlowSeqs" :active-step-names="activeStepNames" />
      </n-card>

      <!-- 精简统计：只留与本角色相关的，去掉资金池/折旧（那是总监视角） -->
      <n-space :size="16" style="margin-top:16px">
        <n-card class="kpi"><n-statistic label="我的待办"><span class="num">{{ myTasks.length }}</span></n-statistic></n-card>
        <n-card class="kpi"><n-statistic label="项目数" :value="overview.length" /></n-card>
        <n-card class="kpi"><n-statistic label="预警" :value="alerts.length" /></n-card>
      </n-space>

      <!-- 待办主角：结构/文本与原首页一致（title=待处理 + router-link a 标签），保证 wizard-workspace e2e 的 todoCard 定位与跳转不变。 -->
      <n-card v-if="hasTasks" title="待处理" style="margin-top:16px">
        <div
          v-for="t in myTasks" :key="t.project_id + '-' + t.step_seq"
          class="task-row"
        >
          <div class="task-left">
            <n-icon :size="20" color="#B45309"><ListChecks /></n-icon>
            <div>
              <div class="task-title">{{ t.project_name }}</div>
              <div class="task-sub">
                Step {{ t.step_seq }} — {{ t.step_name }}
                <n-tag size="tiny" style="margin-left:6px">{{ roleName(t.doer_role) }}</n-tag>
              </div>
            </div>
          </div>
          <router-link :to="'/projects/' + t.project_id + '/workspace'">
            <n-button size="small" type="primary">
              立即处理
              <template #icon><n-icon><ArrowRight /></n-icon></template>
            </n-button>
          </router-link>
        </div>
      </n-card>

      <!-- 空状态：暂无待办 → 角色快捷入口（title 仍为「待处理」以兼容 todoCard 定位） -->
      <n-card v-else title="待处理" style="margin-top:16px">
        <div class="empty-tip">暂无轮到你的步骤。需要主动开始一项工作时，从下面进入：</div>
        <n-space>
          <n-button
            v-for="a in guide.quickActions" :key="a.route"
            size="small" @click="router.push(a.route)"
          >{{ a.label }}</n-button>
          <n-button size="small" quaternary @click="showFlowModal = true">看完整流程</n-button>
        </n-space>
      </n-card>

      <!-- 全新部署快速开始：角色首页此前零引导，新人不知道第一步做什么 -->
      <n-card v-if="isFresh" title="快速开始" style="margin-top:16px" data-testid="quickstart">
        <div style="color:#64748B;font-size:13px;line-height:2">
          <template v-if="isProcurement">
            <div>
              ① 先建主数据：
              <router-link to="/master/suppliers">供应商</router-link> ·
              <router-link to="/master/customers">客户</router-link> ·
              <router-link to="/master/equipment">设备型号</router-link>
            </div>
            <div>② <router-link to="/master/projects">创建项目</router-link>，选择流程模板后系统自动生成向导工作流</div>
            <div>③ 之后每一步都会出现在上方「待办」卡片里，点「立即处理」即可</div>
          </template>
          <template v-else>
            <div>① 项目由<strong>采购对接人</strong>创建后，轮到你的步骤会自动出现在上方「待办」卡片里</div>
            <div>② 点开上方业务流程图，可以提前看看整个链路和你负责的环节</div>
          <div>③ 想快速体验演示数据？请管理员登录后，在首页点「一键载入演示项目」</div>
          </template>
        </div>
      </n-card>
    </template>

    <!-- ===== 原财务首页（admin / 财务总监 / 未知角色 fail-open） ===== -->
    <template v-else>
      <n-space :size="16">
        <n-card class="kpi"><n-statistic label="资金池余额"><span class="num">{{ money(summary.pool_balance) }}</span></n-statistic></n-card>
        <n-card class="kpi"><n-statistic label="项目数" :value="overview.length" /></n-card>
        <n-card class="kpi"><n-statistic label="预警" :value="alerts.length" /></n-card>
        <n-card class="kpi"><n-statistic label="月折旧合计"><span class="num">{{ money(monthlyDep) }}</span></n-statistic></n-card>
      </n-space>

      <n-card v-if="hasTasks" title="待处理" style="margin-top:16px">
        <div v-for="t in myTasks" :key="t.project_id + '-' + t.step_seq"
          style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #F1F5F9"
        >
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
        </div>
        <div style="margin-top:12px">
          <n-button v-if="canLoadDemo" type="primary" size="small" :loading="demoLoading" @click="loadDemo">
            ③ 一键载入演示项目（18 步全链路）
          </n-button>
          <span v-else style="color:#94A3B8;font-size:13px">
            ③ 需要演示数据？请管理员登录后点「一键载入演示项目」。
          </span>
        </div>
      </n-card>

      <n-card v-else size="small" style="margin-top:16px">
        <span style="color:#64748B">暂无待办，一切就绪</span>
      </n-card>

      <!-- 业务流程图：管理员/总监同样需要「先看全局再下钻」 -->
      <n-card style="margin-top:16px" data-testid="flow-map">
        <template #header>
          <span>业务流程图 <span class="tiny" style="color:#94A3B8;font-weight:400">点击节点直达对应页面</span></span>
        </template>
        <FlowMap :active-step-names="activeStepNames" />
      </n-card>

      <!-- ===== 三期 §4.5 经营看板（总监/管理员视角） ===== -->
      <template v-if="board">
        <n-card title="经营看板" style="margin-top:16px" data-testid="business-board">
          <div class="metrics">
            <div class="metric"><div class="m-label">当期合同额</div><div class="num m-val">{{ money(board.metrics.contract_amount_current) }}</div></div>
            <div class="metric"><div class="m-label">累计回款</div><div class="num m-val">{{ money(board.metrics.total_received) }}</div></div>
            <div class="metric"><div class="m-label">开票金额</div><div class="num m-val">{{ money(board.metrics.invoiced_total) }}</div></div>
            <div class="metric"><div class="m-label">确认收入</div><div class="num m-val">{{ money(board.metrics.recognized_total) }}</div></div>
            <div class="metric"><div class="m-label">融资余额</div><div class="num m-val">{{ money(board.metrics.leasing_balance) }}</div></div>
            <div class="metric"><div class="m-label">资金池余额</div><div class="num m-val">{{ money(board.metrics.pool_balance) }}</div></div>
            <div class="metric"><div class="m-label">监管账户余额</div><div class="num m-val">{{ money(board.metrics.supervised_balance) }}</div></div>
            <div class="metric"><div class="m-label">设备交付进度</div><div class="num m-val">{{ board.metrics.device_lit }}/{{ board.metrics.device_total }} 点亮</div></div>
          </div>
        </n-card>

        <div class="grid3">
          <n-card title="待办中心" data-testid="todo-center">
            <n-space vertical :size="6">
              <div v-for="t in board.todo_center" :key="t.kind" class="todo-row" @click="router.push(t.route)">
                <span>{{ t.kind }}</span>
                <n-tag size="small" :bordered="false"
                  :type="t.level === '高危' ? 'error' : t.level === '警告' ? 'warning' : 'success'">
                  {{ t.count }}
                </n-tag>
              </div>
            </n-space>
          </n-card>
          <n-card title="资金预测概览（未来 3 个月·简易版）">
            <n-data-table size="small" :bordered="false"
              :columns="[
                { title: '月份', key: 'month' },
                { title: '流入', key: 'inflow', align: 'right' as const, render: (r: any) => money(r.inflow) },
                { title: '流出', key: 'outflow', align: 'right' as const, render: (r: any) => money(r.outflow) },
                { title: '期末', key: 'closing', align: 'right' as const, render: (r: any) => money(r.closing) },
              ]"
              :data="board.forecast"
              :row-class-name="(r: any) => (r.gap ? 'gap-row' : '')" />
            <div class="tiny" style="color:#94A3B8;margin-top:6px">流入=执行中销售合同月租；流出=当月到期还款+未付采购发票。红行=缺口。接 §4.6 引擎后升级为多场景。</div>
          </n-card>
          <n-card title="EBS 同步状态">
            <n-space vertical :size="6">
              <div class="todo-row"><span>成功</span><n-tag size="small" type="success" :bordered="false">{{ board.ebs.success }}</n-tag></div>
              <div class="todo-row"><span>失败</span><n-tag size="small" :type="board.ebs.failed ? 'error' : 'success'" :bordered="false">{{ board.ebs.failed }}</n-tag></div>
              <div class="todo-row"><span>最近同步</span><span class="tiny">{{ board.ebs.last_synced_at ? String(board.ebs.last_synced_at).slice(0, 19).replace('T', ' ') : '—' }}</span></div>
            </n-space>
            <n-button size="small" quaternary style="margin-top:8px" @click="router.push('/ebs')">进 EBS 监控</n-button>
          </n-card>
        </div>
      </template>

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
    </template>

    <!-- 流程图弹窗（所有角色都可看；节点可点击直达页面，无权节点置灰） -->
    <n-modal v-model:show="showFlowModal" preset="card" title="算力租赁全流程 · 11 步" style="max-width:1000px">
      <div class="flow-intro">
        <template v-if="guide">
          你（<strong>{{ guide.title }}</strong>）负责 {{ guide.flowRange }}，已在下图高亮。点击节点直达对应页面。
        </template>
        <template v-else>管理员 / 总监视角：点击节点直达对应页面。</template>
      </div>
      <FlowMap :highlight-seqs="myFlowSeqs" :active-step-names="activeStepNames" />
    </n-modal>
  </div>
</template>

<style scoped>
.kpi { flex: 1; min-width: 160px; }
.grid { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-top: 16px; }
.grid3 { display: grid; grid-template-columns: 1fr 1.4fr 1fr; gap: 16px; margin-top: 16px; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.metric .m-label { font-size: 12px; color: #94A3B8; }
.metric .m-val { font-size: 18px; font-weight: 600; }
.todo-row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; cursor: pointer; border-bottom: 1px dashed #F1F5F9; }
:deep(.gap-row td) { background: #FEF2F2 !important; color: #B91C1C; }
.span2 { grid-row: span 1; }
@media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

/* 角色职责横幅 */
.role-banner {
  background: linear-gradient(135deg, #FEF3C7, #FFFBEB);
  border: 1px solid #FDE68A;
}
.banner-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.banner-main { min-width: 0; }
.banner-title { font-size: 15px; color: #78350F; }
.banner-title strong { font-size: 17px; color: #B45309; }
.banner-flow { color: #92400E; font-size: 13px; margin-left: 4px; }
.banner-resp { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.banner-actions { display: flex; align-items: center; gap: 4px; flex: none; }

/* 待办主角 */
.task-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 0; border-bottom: 1px solid #F1F5F9;
}
.task-row:last-child { border-bottom: none; }
.task-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.task-title { font-weight: 600; font-size: 14px; }
.task-sub { font-size: 13px; color: #64748B; margin-top: 2px; }
.empty-tip { color: #64748B; font-size: 13px; margin-bottom: 12px; }
.flow-intro { color: #64748B; font-size: 13px; margin-bottom: 20px; }
</style>
