<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NDrawer, NDrawerContent, NFormItem, NInput, NInputNumber,
  NModal, NSpace, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { money } from '../utils/format'

const msg = useMessage()
const processes = ref<any[]>([])
const detail = ref<any | null>(null)
const nodes = ref<any[]>([])
const repayments = ref<any[]>([])
const showDrawer = ref(false)

// 放款表单
const disburseForm = ref({ actual_disbursement_amount: null as number | null, disbursement_date: '', note: '' })
const showDisburse = ref(false)
// 还款确认表单
const confirmTarget = ref<any | null>(null)
const confirmForm = ref({ actual_principal: 0, actual_interest: 0, paid_date: '' })
const showConfirmModal = computed({
  get: () => !!confirmTarget.value,
  set: (v: boolean) => { if (!v) confirmTarget.value = null },
})

async function refresh() {
  try {
    const { data } = await api.get('/leasing/processes')
    processes.value = data.items
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

async function openDetail(row: any) {
  try {
    const [{ data: d }, { data: r }] = await Promise.all([
      api.get(`/leasing/processes/${row.id}`),
      api.get('/repayments', { params: { leasing_process_id: row.id } }),
    ])
    detail.value = d
    nodes.value = d.nodes || []
    repayments.value = r.items || []
    showDrawer.value = true
  } catch { msg.error('加载详情失败') }
}

async function doDisburse() {
  if (!detail.value) return
  if (!disburseForm.value.actual_disbursement_amount || !disburseForm.value.disbursement_date) {
    msg.warning('请填金额和放款日期'); return
  }
  try {
    await api.post(`/leasing/processes/${detail.value.id}/disburse`, disburseForm.value)
    msg.success(`放款成功，已生成 ${detail.value.term_periods} 期还款计划`)
    showDisburse.value = false
    await refresh()
    if (processes.value.find((p) => p.id === detail.value?.id)) {
      await openDetail(processes.value.find((p) => p.id === detail.value!.id)!)
    }
  } catch (e: any) { msg.error(e.response?.data?.detail?.message || '放款失败') }
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
  } catch (e: any) { msg.error(e.response?.data?.detail?.message || '确认失败') }
}

const NODE_COLORS: Record<string, string> = {
  '已完成': '#16A34A', '进行中': '#2563EB', '未开始': '#94A3B8', '卡住': '#DC2626',
}

const processCols = [
  { title: '状态', key: 'status', width: 90, render: (r: any) => statusTag(r.status) },
  { title: '申请额', key: 'total_amount', align: 'right', render: (r: any) => money(r.total_amount) },
  { title: '已放款', key: 'actual_disbursement_amount', align: 'right', render: (r: any) => r.actual_disbursement_amount ? money(r.actual_disbursement_amount) : '—' },
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
  { title: '期', key: 'period', width: 50, align: 'center' },
  { title: '到期日', key: 'due_date', width: 110 },
  { title: '计划本金', key: 'planned_principal', align: 'right', render: (r: any) => money(r.planned_principal) },
  { title: '计划利息', key: 'planned_interest', align: 'right', render: (r: any) => money(r.planned_interest) },
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
    <div style="margin-bottom:14px"><h3>金租流程</h3><div class="muted tiny">共 {{ processes.length }} 条申请</div></div>
    <div class="card" style="padding:4px">
      <n-data-table :columns="processCols" :data="processes" :bordered="false" size="small" striped />
    </div>

    <!-- 详情抽屉 -->
    <n-drawer v-model:show="showDrawer" :width="600" placement="right">
      <n-drawer-content title="金租流程详情" closable>
        <template v-if="detail">
          <n-space>
            <n-tag :type="detail.status === '已放款' ? 'success' : 'warning'" size="small" bordered="false">{{ detail.status }}</n-tag>
            <n-tag v-if="detail.plan_generated" type="info" size="small" bordered="false">{{ detail.term_periods }}期还款计划</n-tag>
          </n-space>

          <!-- 9 节点时间线 -->
          <div class="section-title">流程节点</div>
          <div class="timeline">
            <div v-for="n in nodes" :key="n.seq" class="tl-node">
              <div class="tl-dot" :style="{ background: NODE_COLORS[n.status] || '#94A3B8' }"></div>
              <div class="tl-seq">{{ n.seq }}</div>
              <div class="tl-name">{{ n.node_name }}</div>
              <div class="tl-date">{{ n.actual_date || n.planned_date || '' }}</div>
              <n-tag size="tiny" :bordered="false" :type="n.status === '已完成' ? 'success' : n.status === '卡住' ? 'error' : n.status === '进行中' ? 'info' : 'default'">{{ n.status }}</n-tag>
            </div>
          </div>

          <!-- 放款 -->
          <template v-if="detail.status !== '已放款' && detail.status !== '已拒绝'">
            <div class="section-title">放款操作</div>
            <n-space align="center">
              <n-form-item label="实际放款额" :show-feedback="false">
                <n-input-number v-model:value="disburseForm.actual_disbursement_amount" placeholder="金额" :show-button="false" style="width:160px" />
              </n-form-item>
              <n-form-item label="放款日" :show-feedback="false">
                <n-input v-model:value="disburseForm.disbursement_date" placeholder="YYYY-MM-DD" style="width:130px" />
              </n-form-item>
              <n-button type="primary" @click="doDisburse" :disabled="!disburseForm.actual_disbursement_amount">确认放款</n-button>
            </n-space>
            <div class="muted tiny" style="margin-top:6px">放款将自动生成 {{ detail.term_periods }} 期还款计划 + 1 条资金入金流水</div>
          </template>

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
        <n-form-item label="实际还本"><n-input-number v-model:value="confirmForm.actual_principal" :show-button="false" style="width:100%" /></n-form-item>
        <n-form-item label="实际付息"><n-input-number v-model:value="confirmForm.actual_interest" :show-button="false" style="width:100%" /></n-form-item>
        <n-form-item label="付款日期"><n-input v-model:value="confirmForm.paid_date" placeholder="YYYY-MM-DD" /></n-form-item>
      </n-space>
      <template #footer><n-space justify="end"><n-button @click="confirmTarget = null">取消</n-button><n-button type="primary" @click="doConfirm">确认</n-button></n-space></template>
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
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
