<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCard, NDataTable, NDatePicker, NFormItem, NInput, NInputNumber, NModal,
  NPopconfirm, NSelect, NSpace, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import * as R from '../composables/useResource'
import { money, tsToYmd, ymdToTs } from '../utils/format'
import { errMsg } from '../utils/errMsg'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'

const msg = useMessage()
const route = useRoute()
const summary = ref<any>({ pool_balance: 0, total_in: 0, total_out: 0, by_source: {}, per_project: [] })
const txns = ref<any[]>([])
const projects = ref<any[]>([])
const poolProjects = ref<any[]>([])
const activeTab = ref<'transactions' | 'projects'>('transactions')

const form = reactive({
  project_id: (route.query.project_id as string) || '', source_type: '自有资金', direction: 'IN',
  amount: null as number | null, transaction_date: '', note: '', pool: 'OWN',
})
const SOURCE_OPTS = ['自有资金', '银行流贷', '金租融资', '租金收入', '还款'].map((v) => ({ label: v, value: v }))
const DIR_OPTS = [{ label: '入金 IN', value: 'IN' }, { label: '出金 OUT', value: 'OUT' }]
// 四期 W4：资金池
const POOL_OPTS = [{ label: '自有资金池', value: 'OWN' }, { label: '金租池', value: 'LEASING' }, { label: '银行池', value: 'BANK' }, { label: '预付款池(挂账)', value: 'PREPAY' }]
const CASH_POOL_OPTS = [{ label: '银行池', value: 'BANK' }, { label: '金租池', value: 'LEASING' }, { label: '自有池', value: 'OWN' }]

async function refresh() {
  try {
    const [s, t, p, pp, al] = await Promise.all([
      api.get('/capital/summary'), api.get('/capital/transactions'), api.get('/projects'),
      api.get('/capital/pool-by-project'), api.get('/capital/allocations'),
    ])
    summary.value = s.data; txns.value = t.data.items; projects.value = p.data.items
    poolProjects.value = pp.data.items; allocRecs.value = (al.data.items || []).map((a: any) => ({...a, id: a.id}))
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

const projectOpts = () => projects.value.map((p: any) => ({ label: p.name, value: p.id }))
const projectName = (id: string) => projects.value.find((p: any) => p.id === id)?.name || id.slice(0, 8) + '…'

async function submit() {
  if (!form.project_id || !form.amount || !form.transaction_date) { msg.warning('请填齐 项目/金额/日期'); return }
  try {
    await R.createRes('/capital/transactions', { ...form })
    msg.success('已记账'); await refresh()
    form.amount = null; form.note = ''
  } catch (e: any) { msg.error(errMsg(e)) }
}

// 流水红冲
async function reverseTxn(row: any) {
  try {
    await api.post(`/capital/transactions/${row.id}/reverse`)
    msg.success('已红冲（生成等额反向流水）'); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// —— 四期 W4：资金池分池 ——
const poolCards = computed(() => {
  const bp = summary.value.by_pool || {}
  return ['LEASING', 'BANK', 'PREPAY', 'OWN'].map((k) => ({
    key: k, label: (bp[k] && bp[k].label) || k, net: (bp[k] && bp[k].net) ?? 0,
  }))
})

// 池操作：记银行借款 / 还银行 / 预付 / 预付退回 / 预付核销
const showPoolAct = ref(false)
const poolAct = reactive({ type: '' as string, project_id: '' as string, amount: null as number | null, transaction_date: tsToYmd(Date.now()), pool: 'BANK', note: '' })
const POOL_ACT_TITLE: Record<string, string> = {
  'bank-loan': '记银行借款（银行池 +）', 'repay-bank': '还银行（银行池 −）',
  'prepay': '预付（现金池 → 预付款池挂账）', 'prepay-refund': '预付退回（预付款池 → 现金池）',
  'prepay-offset': '预付核销（预付款池 ↓，抵应付）',
}
const needPool = computed(() => poolAct.type === 'prepay' || poolAct.type === 'prepay-refund')
const poolFieldLabel = computed(() => (poolAct.type === 'prepay' ? '从哪个池预付' : '退回到哪个池'))
function openPoolAct(t: string) {
  poolAct.type = t; poolAct.amount = null; poolAct.note = ''
  poolAct.project_id = form.project_id || (projects.value[0]?.id ?? '')
  showPoolAct.value = true
}
async function submitPoolAct() {
  if (!poolAct.project_id || !poolAct.amount || !poolAct.transaction_date) { msg.warning('请填齐 项目/金额/日期'); return }
  const base: any = { project_id: poolAct.project_id, amount: poolAct.amount, transaction_date: poolAct.transaction_date, note: poolAct.note || null }
  try {
    if (poolAct.type === 'bank-loan') await api.post('/capital/bank-loan', base)
    else if (poolAct.type === 'repay-bank') await api.post('/capital/repay-bank', base)
    else if (poolAct.type === 'prepay') await api.post('/capital/prepayment', { ...base, from_pool: poolAct.pool })
    else if (poolAct.type === 'prepay-refund') await api.post('/capital/prepayment/refund', { ...base, to_pool: poolAct.pool })
    else if (poolAct.type === 'prepay-offset') await api.post('/capital/prepayment/offset', base)
    msg.success('已记账'); showPoolAct.value = false; await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// —— 调配 / 归还 ——
interface AllocRec { id: string; from_project_id: string; to_project_id: string; amount: number; allocation_date: string; status: string; reason?: string }
const allocRecs = ref<AllocRec[]>([])

const showAlloc = ref(false)
const allocForm = reactive({
  from_project_id: '' as string, to_project_id: '' as string,
  amount: null as number | null, allocation_date: tsToYmd(Date.now()),
  expected_return_date: '', reason: '',
})
async function submitAlloc() {
  const f = allocForm
  if (!f.from_project_id || !f.to_project_id || !f.amount || !f.allocation_date) {
    msg.warning('请填齐 调出项目/调入项目/金额/日期'); return
  }
  try {
    const { data } = await api.post('/capital/allocate', {
      from_project_id: f.from_project_id, to_project_id: f.to_project_id,
      amount: f.amount, allocation_date: f.allocation_date,
      expected_return_date: f.expected_return_date || null, reason: f.reason || null,
    })
    msg.success('调配成功（已生成调出/调入两条流水）')
    showAlloc.value = false
    allocForm.amount = null; allocForm.reason = ''
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

const showReturn = ref(false)
const returnForm = reactive({ allocation_id: null as string | null, return_date: tsToYmd(Date.now()) })
const returnOpts = computed(() => allocRecs.value.filter((a) => a.status === '已调配' || a.status === '逾期').map((a) => ({
  label: `${projectName(a.from_project_id)} → ${projectName(a.to_project_id)} · ${money(a.amount)} · ${a.allocation_date}`,
  value: a.id,
})))
async function submitReturn() {
  if (!returnForm.allocation_id || !returnForm.return_date) { msg.warning('请选择调配记录和归还日期'); return }
  try {
    await api.post(`/capital/allocations/${returnForm.allocation_id}/return`, { return_date: returnForm.return_date })
    msg.success('已归还（生成反向两条流水）')
    showReturn.value = false; returnForm.allocation_id = null
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
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
  { title: '项目', key: 'project_id', width: 140, render: (r: any) => r.project_id ? projectName(r.project_id) : '—' },
  { title: '来源', key: 'source_type', width: 100 },
  { title: '资金池', key: 'pool', width: 90, render: (r: any) => ({ OWN: '自有', LEASING: '金租', BANK: '银行', PREPAY: '预付' } as any)[r.pool] || r.pool || '自有' },
  { title: '方向', key: 'direction', width: 70 },
  { title: '金额', key: 'amount', align: 'right' as const, className: 'num', render: (r: any) => money(r.amount) },
  { title: '摘要', key: 'note', render: (r: any) => (r.is_reversal ? `【红冲】${r.note || ''}` : r.note) as string },
  { title: '操作', key: '__op', width: 70, render: (r: any) =>
      r.is_reversal ? null : h(NPopconfirm, { onPositiveClick: () => reverseTxn(r) }, {
        trigger: () => h(NButton, { size: 'tiny', type: 'error', quaternary: true }, () => '红冲'),
        default: () => '红冲将生成等额反向流水抵消该记录（原记录保留留痕），不可撤销。确认？',
      }) },
]
</script>

<template>
  <div>
    <n-space :size="16">
      <n-card class="kpi"><div class="kpi-label">资金池余额</div><div class="kpi-val num">{{ money(summary.pool_balance) }}</div></n-card>
      <n-card class="kpi"><div class="kpi-label">累计入金</div><div class="kpi-val num in">{{ money(summary.total_in) }}</div></n-card>
      <n-card class="kpi"><div class="kpi-label">累计出金</div><div class="kpi-val num out">{{ money(summary.total_out) }}</div></n-card>
    </n-space>

    <!-- 四期 W4：4 资金池余额 -->
    <n-space :size="16" style="margin-top:12px">
      <n-card v-for="pc in poolCards" :key="pc.key" class="kpi pool-kpi">
        <div class="kpi-label">{{ pc.label }}</div>
        <div class="kpi-val num">{{ money(pc.net) }}</div>
      </n-card>
    </n-space>
    <n-card :bordered="false" size="small" style="margin-top:8px">
      <n-space wrap>
        <span class="muted tiny" style="align-self:center">资金池操作：</span>
        <n-button size="small" @click="openPoolAct('bank-loan')">记银行借款</n-button>
        <n-button size="small" @click="openPoolAct('repay-bank')">还银行</n-button>
        <n-button size="small" @click="openPoolAct('prepay')">预付</n-button>
        <n-button size="small" @click="openPoolAct('prepay-refund')">预付退回</n-button>
        <n-button size="small" @click="openPoolAct('prepay-offset')">预付核销</n-button>
      </n-space>
    </n-card>

    <!-- v3.2 Tab：流水 / 分项目 -->
    <n-card style="margin-top:16px" :bordered="false" size="small">
      <n-space>
        <n-button :type="activeTab==='transactions'?'primary':'default'" size="small" @click="activeTab='transactions'">流水</n-button>
        <n-button :type="activeTab==='projects'?'primary':'default'" size="small" @click="activeTab='projects'">分项目</n-button>
      </n-space>
    </n-card>

    <!-- 分项目视图 -->
    <n-card v-if="activeTab==='projects'" title="资金池分项目" style="margin-top:8px">
      <n-dataTable :columns="[
        {title:'项目',key:'project_name'},
        {title:'净头寸',key:'net_position',align:'right',className:'num',render:(r:any)=>money(r.net_position)},
        {title:'可调出',key:'allocatable',align:'right',className:'num',render:(r:any)=>money(r.allocatable)},
        {title:'在途调配',key:'in_transit',align:'right',className:'num',render:(r:any)=>money(r.in_transit)},
        {title:'近30天入',key:'recent_30d_in',align:'right',className:'num',render:(r:any)=>money(r.recent_30d_in)},
        {title:'近30天出',key:'recent_30d_out',align:'right',className:'num',render:(r:any)=>money(r.recent_30d_out)},
        {title:'操作',key:'__op',width:70,render:(r:any)=>h(NButton,{size:'tiny',onClick:()=>{allocForm.from_project_id=r.project_id;showAlloc=true}},()=>'调配')},
      ]" :data="poolProjects" :bordered="false" />
    </n-card>

    <div class="grid" v-show="activeTab==='transactions'">
      <n-card title="记一笔">
        <n-space wrap :size="12">
          <n-form-item label="项目" :show-feedback="false">
            <n-select v-model:value="form.project_id" :options="projectOpts()" style="width:180px" placeholder="选项目" />
          </n-form-item>
          <n-form-item label="来源" :show-feedback="false">
            <n-select v-model:value="form.source_type" :options="SOURCE_OPTS" style="width:130px" />
          </n-form-item>
          <n-form-item label="方向" :show-feedback="false">
            <n-select v-model:value="form.direction" :options="DIR_OPTS" style="width:110px" />
          </n-form-item>
          <n-form-item label="资金池" :show-feedback="false">
            <n-select v-model:value="form.pool" :options="POOL_OPTS" style="width:130px" />
          </n-form-item>
          <n-form-item label="金额(元)" :show-feedback="false">
            <n-input-number v-model:value="form.amount" style="width:150px" :show-button="false" placeholder="金额" />
          </n-form-item>
          <n-form-item label="日期" :show-feedback="false">
            <n-date-picker type="date" :value="ymdToTs(form.transaction_date)"
              @update:value="(ts: number | null) => form.transaction_date = tsToYmd(ts)" style="width:150px" />
          </n-form-item>
          <n-form-item label="摘要" :show-feedback="false">
            <n-input v-model:value="form.note" placeholder="可选" style="width:160px" />
          </n-form-item>
          <n-button type="primary" @click="submit">记一笔</n-button>
          <n-button @click="showAlloc = true">调配</n-button>
          <n-button @click="showReturn = true">归还</n-button>
        </n-space>
      </n-card>
      <n-card title="收入构成（按来源）">
        <EChart :option="pieOption" height="240px" />
      </n-card>
    </div>

    <n-card title="资金流水" v-show="activeTab==='transactions'" style="margin-top:16px">
      <n-data-table :columns="txnCols" :data="txns" :bordered="false" size="small" striped :pagination="{ pageSize: 12 }">
        <template #empty>
          <EmptyState description="还没有记录，在上方「记一笔」录入第一笔即可" />
        </template>
      </n-data-table>
    </n-card>

    <!-- 调配弹窗 -->
    <n-modal v-model:show="showAlloc" preset="card" title="项目间资金调配" style="width:460px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="调出项目">
          <n-select v-model:value="allocForm.from_project_id" :options="projectOpts()" placeholder="选调出项目" filterable />
        </n-form-item>
        <n-form-item label="调入项目">
          <n-select v-model:value="allocForm.to_project_id" :options="projectOpts()" placeholder="选调入项目" filterable />
        </n-form-item>
        <n-space>
          <n-form-item label="金额(元)"><n-input-number v-model:value="allocForm.amount" :show-button="false" style="width:150px" /></n-form-item>
          <n-form-item label="调配日期">
            <n-date-picker type="date" :value="ymdToTs(allocForm.allocation_date)"
              @update:value="(ts: number | null) => allocForm.allocation_date = tsToYmd(ts)" style="width:150px" />
          </n-form-item>
        </n-space>
        <n-form-item label="预计归还日（可选）">
          <n-date-picker type="date" clearable :value="ymdToTs(allocForm.expected_return_date)"
            @update:value="(ts: number | null) => allocForm.expected_return_date = tsToYmd(ts)" style="width:150px" />
        </n-form-item>
        <n-form-item label="说明"><n-input v-model:value="allocForm.reason" placeholder="可选" /></n-form-item>
        <div class="muted tiny">将原子生成「调出 OUT + 调入 IN」两条流水；调出项目可调余额不足会被拦截。</div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAlloc = false">取消</n-button>
          <n-button type="primary" @click="submitAlloc">确认调配</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 归还弹窗 -->
    <n-modal v-model:show="showReturn" preset="card" title="调配归还" style="width:440px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="调配记录">
          <n-select v-model:value="returnForm.allocation_id" :options="returnOpts" placeholder="选待归还的调配" filterable />
        </n-form-item>
        <n-form-item label="归还日期">
          <n-date-picker type="date" :value="ymdToTs(returnForm.return_date)"
            @update:value="(ts: number | null) => returnForm.return_date = tsToYmd(ts)" style="width:150px" />
        </n-form-item>
        <div class="muted tiny">列出所有未归还的调配记录。归还将生成「调入方 OUT + 调出方 IN」反向流水。</div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showReturn = false">取消</n-button>
          <n-button type="primary" :disabled="!returnForm.allocation_id" @click="submitReturn">确认归还</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 四期 W4：资金池操作弹窗（记借款/还银行/预付/退回/核销） -->
    <n-modal v-model:show="showPoolAct" preset="card" :title="POOL_ACT_TITLE[poolAct.type] || '资金池操作'" style="width:460px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="项目">
          <n-select v-model:value="poolAct.project_id" :options="projectOpts()" placeholder="选项目" filterable />
        </n-form-item>
        <n-form-item v-if="needPool" :label="poolFieldLabel">
          <n-select v-model:value="poolAct.pool" :options="CASH_POOL_OPTS" />
        </n-form-item>
        <n-space>
          <n-form-item label="金额(元)"><n-input-number v-model:value="poolAct.amount" :show-button="false" style="width:170px" /></n-form-item>
          <n-form-item label="日期">
            <n-date-picker type="date" :value="ymdToTs(poolAct.transaction_date)"
              @update:value="(ts: number | null) => poolAct.transaction_date = tsToYmd(ts)" style="width:150px" />
          </n-form-item>
        </n-space>
        <n-form-item label="摘要"><n-input v-model:value="poolAct.note" placeholder="可选" /></n-form-item>
        <div class="muted tiny">
          <template v-if="poolAct.type==='bank-loan'">银行借款入「银行池」（持有借款余额增加）。</template>
          <template v-else-if="poolAct.type==='repay-bank'">从「银行池」出钱还银行，余额不足会被拦截。</template>
          <template v-else-if="poolAct.type==='prepay'">从所选现金池出钱预付给供应商，同时「预付款池」挂账增加。</template>
          <template v-else-if="poolAct.type==='prepay-refund'">供应商退回预付：「预付款池」挂账减少，现金回到所选池。</template>
          <template v-else-if="poolAct.type==='prepay-offset'">拿到采购发票后核销：「预付款池」挂账减少，抵减应付（不动现金）。</template>
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showPoolAct = false">取消</n-button>
          <n-button type="primary" @click="submitPoolAct">确认</n-button>
        </n-space>
      </template>
    </n-modal>
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
