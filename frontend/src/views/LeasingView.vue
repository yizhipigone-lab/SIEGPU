<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCard, NDataTable, NDatePicker, NDrawer, NDrawerContent, NFormItem, NInput, NInputNumber,
  NModal, NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { money, tsToYmd, ymdToTs } from '../utils/format'
import { errMsg } from '../utils/errMsg'
import EmptyState from '../components/EmptyState.vue'

const msg = useMessage()
const route = useRoute()
const processes = ref<any[]>([])
const detail = ref<any | null>(null)
const nodes = ref<any[]>([])
const repayments = ref<any[]>([])
const showDrawer = ref(false)

// 放款记录（分次放款）
const disbursements = ref<any[]>([])
const acceptances = ref<any[]>([])
const showAddDisb = ref(false)
const addDisbForm = ref({ amount: null as number | null, disbursement_date: '', note: '', acceptance_id: '' as string })
// 还款确认表单
const confirmTarget = ref<any | null>(null)
const confirmForm = ref({ actual_principal: 0, actual_interest: 0, paid_date: '' })
const showConfirmModal = computed({
  get: () => !!confirmTarget.value,
  set: (v: boolean) => { if (!v) confirmTarget.value = null },
})

// 新建金租申请
const showCreate = ref(false)
const projects = ref<any[]>([])
const fundSuppliers = ref<any[]>([])
const createForm = ref({
  project_id: '' as string, supplier_id: '' as string,
  total_amount: null as number | null, annual_rate: null as number | null,
  term_periods: null as number | null, payment_freq: '月' as string,
  repayment_method: '等额本息' as string, start_date: '',
  leasing_mode: null as string | null,      // W7-8 融资分类三字段
  financing_type: null as string | null,
  materials_note: '' as string,
})

// 节点标记卡住
const stuckTarget = ref<any | null>(null)
const stuckReason = ref('')
const showStuck = computed({
  get: () => !!stuckTarget.value,
  set: (v: boolean) => { if (!v) { stuckTarget.value = null; stuckReason.value = '' } },
})

async function refresh() {
  try {
    const [{ data: lp }, { data: proj }, { data: sup }] = await Promise.all([
      api.get('/leasing/processes'), api.get('/projects'), api.get('/suppliers'),
    ])
    processes.value = lp.items
    projects.value = proj.items
    fundSuppliers.value = (sup.items || []).filter((s: any) => s.type === '资金供应商')
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

function openCreate() {
  createForm.value = {
    project_id: (route.query.project_id as string) || '', supplier_id: '', total_amount: null, annual_rate: null,
    term_periods: null, payment_freq: '月', repayment_method: '等额本息', start_date: '',
    leasing_mode: null, financing_type: null, materials_note: '',
  }
  showCreate.value = true
}

async function doCreate() {
  const f = createForm.value
  if (!f.project_id || !f.supplier_id) { msg.warning('请选择项目和金租公司'); return }
  if (!f.total_amount) { msg.warning('请填申请金额'); return }
  try {
    await api.post('/leasing/processes', {
      project_id: f.project_id, supplier_id: f.supplier_id, total_amount: f.total_amount,
      annual_rate: f.annual_rate, term_periods: f.term_periods,
      payment_freq: f.payment_freq, repayment_method: f.repayment_method,
      start_date: f.start_date || null,
      leasing_mode: f.leasing_mode, financing_type: f.financing_type,
      materials: f.materials_note.trim() ? { note: f.materials_note.trim() } : null,
    })
    msg.success('金租申请已创建')
    showCreate.value = false
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// 节点推进：进行中/已完成；卡住走弹窗填原因
async function advanceNode(node: any, status: '进行中' | '已完成') {
  try {
    await api.patch(`/leasing/nodes/${node.id}`, {
      status, actual_date: new Date().toISOString().slice(0, 10),
    })
    msg.success(status === '已完成' ? `节点「${node.node_name}」已完成` : `节点「${node.node_name}」已开始`)
    if (detail.value) await openDetail(detail.value)
  } catch (e: any) { msg.error(errMsg(e)) }
}

function openStuck(node: any) { stuckTarget.value = node; stuckReason.value = node.stuck_reason || '' }

async function doStuck() {
  if (!stuckTarget.value) return
  if (!stuckReason.value.trim()) { msg.warning('请填卡住原因'); return }
  try {
    await api.patch(`/leasing/nodes/${stuckTarget.value.id}`, {
      status: '卡住', stuck_reason: stuckReason.value,
    })
    msg.success(`节点「${stuckTarget.value.node_name}」已标记卡住`)
    stuckTarget.value = null; stuckReason.value = ''
    if (detail.value) await openDetail(detail.value)
  } catch (e: any) { msg.error(errMsg(e)) }
}

async function openDetail(row: any) {
  try {
    const [{ data: d }, { data: r }, { data: ds }, { data: ac }] = await Promise.all([
      api.get(`/leasing/processes/${row.id}`),
      api.get('/repayments', { params: { leasing_process_id: row.id } }),
      api.get(`/leasing/processes/${row.id}/disbursements`),
      api.get('/acceptances', { params: { project_id: row.project_id, acceptance_type: '采购验收' } }),
    ])
    detail.value = d
    nodes.value = d.nodes || []
    repayments.value = r.items || []
    disbursements.value = ds.items || []
    acceptances.value = (ac || []).filter((a: any) => a.status === '已通过')
    showDrawer.value = true
  } catch { msg.error('加载详情失败') }
}

function accLabel(id: string | null): string {
  if (!id) return ''
  const a = acceptances.value.find((x: any) => x.id === id)
  return a ? `验收 ${a.acceptance_date || ''} · ${a.quantity_accepted}台` : '验收'
}

function openAddDisb() {
  addDisbForm.value = { amount: null, disbursement_date: '', note: '', acceptance_id: '' }
  showAddDisb.value = true
}

async function doAddDisb() {
  if (!detail.value) return
  const f = addDisbForm.value
  if (!f.acceptance_id) { msg.warning('请选择本次放款对应的采购验收'); return }
  if (!f.amount || !f.disbursement_date) { msg.warning('请填放款额和实际放款日'); return }
  try {
    await api.post(`/leasing/processes/${detail.value.id}/disbursements`, {
      amount: f.amount, disbursement_date: f.disbursement_date,
      acceptance_id: f.acceptance_id, note: f.note || null,
    })
    msg.success('放款已登记，已生成该笔还款计划')
    showAddDisb.value = false
    if (detail.value) await openDetail(detail.value)
  } catch (e: any) { msg.error(errMsg(e)) }
}

function openConfirm(r: any) {
  confirmTarget.value = r
  confirmForm.value = {
    actual_principal: Number(r.planned_principal), actual_interest: Number(r.planned_interest), paid_date: '',
  }
}

async function doConfirm() {
  if (!confirmTarget.value || !confirmForm.value.paid_date) { msg.warning('请填付款日期'); return }
  try {
    await api.patch(`/repayments/${confirmTarget.value.id}`, confirmForm.value)
    msg.success('还款已确认')
    confirmTarget.value = null
    if (detail.value) await openDetail(processes.value.find((p) => p.id === detail.value!.id)!)
  } catch (e: any) { msg.error(errMsg(e)) }
}

const NODE_COLORS: Record<string, string> = {
  '已完成': '#16A34A', '进行中': '#2563EB', '未开始': '#94A3B8', '卡住': '#DC2626',
}

const processCols = [
  { title: '状态', key: 'status', width: 90, render: (r: any) => statusTag(r.status) },
  { title: '申请额', key: 'total_amount', align: 'right' as const, render: (r: any) => money(r.total_amount) },
  { title: '已放款', key: 'actual_disbursement_amount', align: 'right' as const, render: (r: any) => r.actual_disbursement_amount ? money(r.actual_disbursement_amount) : '—' },
  { title: '放款日', key: 'disbursement_date', render: (r: any) => r.disbursement_date || '—' },
  { title: '还款计划', key: 'plan_generated', width: 100, render: (r: any) => r.plan_generated ? `${r.term_periods}期已生成` : '—' },
  { title: '操作', key: '__op', width: 80, render: (r: any) => opBtn(r) },
]

function statusTag(s: string) {
  const map: Record<string, any> = { '已放款': 'success', '已批': 'info', '进行中': 'warning', '已拒绝': 'error' }
  return h(NTag, { size: 'small', type: map[s] || 'default', bordered: false }, () => s)
}
function opBtn(r: any) {
  return h(NButton, { size: 'tiny', quaternary: true, onClick: () => openDetail(r) }, () => '详情')
}

const repayCols = [
  { title: '期', key: 'period', width: 50, align: 'center' as const },
  { title: '到期日', key: 'due_date', width: 110 },
  { title: '计划本金', key: 'planned_principal', align: 'right' as const, render: (r: any) => money(r.planned_principal) },
  { title: '计划利息', key: 'planned_interest', align: 'right' as const, render: (r: any) => money(r.planned_interest) },
  { title: '状态', key: 'status', width: 80, render: (r: any) => statusTag(r.status) },
  { title: '操作', key: '__op', width: 90, render: (r: any) =>
    r.status === '待还'
      ? h(NButton, { size: 'tiny', type: 'primary', onClick: () => openConfirm(r) }, () => '确认还款')
      : h('span', { style: 'color:#94A3B8' }, r.paid_date || '')
  },
]
</script>

<template>
  <div>
    <div style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center">
      <div><h3 style="margin:0">金租流程</h3><div class="muted tiny">共 {{ processes.length }} 条申请</div></div>
      <n-button type="primary" @click="openCreate">新建金租申请</n-button>
    </div>
    <div class="card" style="padding:4px">
      <n-data-table :columns="processCols" :data="processes" :bordered="false" size="small" striped>
        <template #empty>
          <EmptyState description="还没有金租申请，点击右上角「新建金租申请」即可发起金租融资" />
        </template>
      </n-data-table>
    </div>

    <!-- 详情抽屉 -->
    <n-drawer v-model:show="showDrawer" :width="600" placement="right">
      <n-drawer-content title="金租流程详情" closable>
        <template v-if="detail">
          <n-space>
            <n-tag :type="detail.status === '已放款' ? 'success' : 'warning'" size="small" :bordered="false">{{ detail.status }}</n-tag>
            <n-tag v-if="detail.plan_generated" type="info" size="small" :bordered="false">{{ detail.term_periods }}期还款计划</n-tag>
            <n-tag v-if="detail.leasing_mode" size="small" :bordered="false">模式：{{ detail.leasing_mode }}</n-tag>
            <n-tag v-if="detail.financing_type" size="small" :bordered="false" type="info">融资：{{ detail.financing_type }}</n-tag>
          </n-space>
          <div v-if="detail.materials" class="muted tiny" style="margin-top:6px">
            材料：{{ detail.materials.note || JSON.stringify(detail.materials) }}
          </div>

          <!-- 9 节点时间线 -->
          <div class="section-title">流程节点</div>
          <div class="timeline">
            <div v-for="n in nodes" :key="n.seq" class="tl-node">
              <div class="tl-dot" :style="{ background: NODE_COLORS[n.status] || '#94A3B8' }"></div>
              <div class="tl-seq">{{ n.seq }}</div>
              <div class="tl-name">{{ n.node_name }}</div>
              <div class="tl-date">{{ n.actual_date || n.planned_date || '' }}</div>
              <n-tag size="tiny" :bordered="false" :type="n.status === '已完成' ? 'success' : n.status === '卡住' ? 'error' : n.status === '进行中' ? 'info' : 'default'">{{ n.status }}</n-tag>
              <div v-if="n.status !== '已完成'" class="tl-ops">
                <n-button v-if="n.status === '未开始'" size="tiny" quaternary type="info" @click="advanceNode(n, '进行中')">开始</n-button>
                <n-button size="tiny" quaternary type="success" @click="advanceNode(n, '已完成')">完成</n-button>
                <n-button v-if="n.status !== '卡住'" size="tiny" quaternary type="error" @click="openStuck(n)">卡住</n-button>
              </div>
              <div v-if="n.status === '卡住' && n.stuck_reason" class="tl-date" style="color:#DC2626">{{ n.stuck_reason }}</div>
            </div>
          </div>

          <!-- 放款记录（分次放款） -->
          <div class="section-title" style="display:flex;justify-content:space-between;align-items:center">
            <span>放款记录（{{ disbursements.length }} 笔）</span>
            <n-button size="small" type="primary" @click="openAddDisb">新增放款</n-button>
          </div>
          <div v-if="disbursements.length === 0" class="muted tiny" style="padding:8px 0">暂无放款记录。完成采购验收后点「新增放款」登记到账</div>
          <div v-else>
            <div v-for="dd in disbursements" :key="dd.id" style="padding:8px 0;border-bottom:1px dashed #F1F5F9">
              <n-space align="center">
                <span class="num" style="font-weight:600">{{ money(dd.amount) }}</span>
                <n-tag size="tiny" :bordered="false" type="success">{{ dd.disbursement_date }}</n-tag>
                <n-tag v-if="dd.acceptance_id" size="tiny" :bordered="false">{{ accLabel(dd.acceptance_id) }}</n-tag>
                <span class="muted tiny">{{ dd.note || '' }}</span>
              </n-space>
            </div>
          </div>

          <!-- 还款计划 -->
          <template v-if="repayments.length">
            <div class="section-title">还款计划（{{ repayments.length }} 期）</div>
            <n-data-table :columns="repayCols" :data="repayments" :bordered="false" size="small" striped :max-height="400" />
          </template>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- 还款确认弹窗 -->
    <n-modal v-model:show="showConfirmModal" preset="card" title="确认还款" style="width:380px">
      <n-space vertical>
        <n-form-item label="实际还本(元)"><n-input-number v-model:value="confirmForm.actual_principal" :show-button="false" style="width:100%" /></n-form-item>
        <n-form-item label="实际付息(元)"><n-input-number v-model:value="confirmForm.actual_interest" :show-button="false" style="width:100%" /></n-form-item>
        <n-form-item label="付款日期">
          <n-date-picker type="date" style="width:100%" :value="ymdToTs(confirmForm.paid_date)"
            @update:value="(ts: number | null) => confirmForm.paid_date = tsToYmd(ts)" />
        </n-form-item>
      </n-space>
      <template #footer><n-space justify="end"><n-button @click="confirmTarget = null">取消</n-button><n-button type="primary" @click="doConfirm">确认</n-button></n-space></template>
    </n-modal>

    <!-- 新增放款 -->
    <n-modal v-model:show="showAddDisb" preset="card" title="新增放款" style="width:400px">
      <n-space vertical :size="12">
        <n-form-item label="对应采购验收">
          <n-select v-model:value="addDisbForm.acceptance_id" filterable placeholder="选择本次放款对应的验收批次"
            :options="acceptances.map((a: any) => ({ label: `采购验收 ${a.acceptance_date || ''} · ${a.quantity_accepted}台`, value: a.id }))" />
        </n-form-item>
        <n-form-item label="放款额(元)"><n-input-number v-model:value="addDisbForm.amount" :show-button="false" style="width:100%" /></n-form-item>
        <n-form-item label="实际放款日"><n-date-picker type="date" style="width:100%" :value="ymdToTs(addDisbForm.disbursement_date)" @update:value="(ts: number | null) => addDisbForm.disbursement_date = tsToYmd(ts)" /></n-form-item>
        <n-form-item label="备注"><n-input v-model:value="addDisbForm.note" /></n-form-item>
      </n-space>
      <template #footer><n-space justify="end"><n-button @click="showAddDisb = false">取消</n-button><n-button type="primary" @click="doAddDisb">确认放款</n-button></n-space></template>
    </n-modal>

    <!-- 新建金租申请 -->
    <n-modal v-model:show="showCreate" preset="card" title="新建金租申请" style="width:520px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="项目">
          <n-select v-model:value="createForm.project_id" :options="projects.map((p: any) => ({ label: p.name, value: p.id }))" placeholder="选项目" filterable />
        </n-form-item>
        <n-form-item label="金租公司（资金供应商）">
          <n-select v-model:value="createForm.supplier_id" :options="fundSuppliers.map((s: any) => ({ label: s.name, value: s.id }))" placeholder="选金租公司" filterable />
        </n-form-item>
        <n-space>
          <n-form-item label="申请金额(元)"><n-input-number v-model:value="createForm.total_amount" :show-button="false" style="width:170px" /></n-form-item>
          <n-form-item label="年利率(小数,如0.04)"><n-input-number v-model:value="createForm.annual_rate" :step="0.005" :show-button="false" style="width:110px" /></n-form-item>
          <n-form-item label="期数(期)"><n-input-number v-model:value="createForm.term_periods" :min="1" style="width:90px" /></n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="还款频率">
            <n-select v-model:value="createForm.payment_freq" :options="[{ label: '月', value: '月' }, { label: '季', value: '季' }, { label: '半年', value: '半年' }]" style="width:100px" />
          </n-form-item>
          <n-form-item label="还款方式">
            <n-select v-model:value="createForm.repayment_method" :options="[{ label: '等额本息', value: '等额本息' }, { label: '等额本金', value: '等额本金' }]" style="width:120px" />
          </n-form-item>
          <n-form-item label="预计放款日">
            <n-date-picker type="date" :value="ymdToTs(createForm.start_date)"
              @update:value="(ts: number | null) => createForm.start_date = tsToYmd(ts)" style="width:150px" />
          </n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="金租模式">
            <n-select v-model:value="createForm.leasing_mode" :options="[{ label: '自有', value: '自有' }, { label: '直租', value: '直租' }, { label: '售后回租', value: '售后回租' }]" placeholder="选模式" clearable style="width:130px" />
          </n-form-item>
          <n-form-item label="融资类型">
            <n-select v-model:value="createForm.financing_type" :options="[{ label: '金租直租', value: '金租直租' }, { label: '金租回租', value: '金租回租' }, { label: '银行流贷', value: '银行流贷' }, { label: '项目贷款', value: '项目贷款' }]" placeholder="选类型" clearable style="width:140px" />
          </n-form-item>
        </n-space>
        <n-form-item label="材料备注">
          <n-input v-model:value="createForm.materials_note" placeholder="如：合同/发票/权属证明（选填）" />
        </n-form-item>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" @click="doCreate">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 节点卡住原因 -->
    <n-modal v-model:show="showStuck" preset="card" title="标记节点卡住" style="width:380px">
      <n-form-item label="卡住原因">
        <n-input v-model:value="stuckReason" type="textarea" :rows="2" placeholder="必填" />
      </n-form-item>
      <template #footer>
        <n-space justify="end">
          <n-button @click="stuckTarget = null">取消</n-button>
          <n-button type="error" @click="doStuck">标记卡住</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.section-title { margin: 20px 0 10px; font-weight: 600; font-size: 14px; color: var(--c-text-2); }
.timeline { display: flex; flex-wrap: wrap; gap: 10px; }
.tl-node { display: flex; flex-direction: column; align-items: center; width: 56px; text-align: center; }
.tl-dot { width: 20px; height: 20px; border-radius: 50%; margin-bottom: 4px; }
.tl-seq { font-size: 10px; color: var(--c-text-3); }
.tl-name { font-size: 11px; line-height: 1.2; margin-bottom: 2px; }
.tl-date { font-size: 9px; color: var(--c-text-3); margin-bottom: 2px; }
.tl-ops { display: flex; flex-direction: column; gap: 2px; margin-top: 2px; }
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
