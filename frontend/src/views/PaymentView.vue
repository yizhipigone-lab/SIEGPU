<script setup lang="ts">
// 二期 W11-12：付款三重管控（申请 → 审批 → 登记 → 核销）+ 审批中心。
// 三区块：审批中心（待审批通过/驳回）/ 付款申请（新增、登记、核销）/ 核销记录。
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton, NCard, NCheckbox, NDataTable, NDatePicker, NForm, NFormItem, NInput, NInputNumber, NModal,
  NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money, tsToYmd, ymdToTs } from '../utils/format'

const msg = useMessage()
const requests = ref<any[]>([])
const approvals = ref<any[]>([])
const settlements = ref<any[]>([])
const projects = ref<any[]>([])
const invoices = ref<any[]>([])

async function refresh() {
  try {
    const [r, a, s] = await Promise.all([
      api.get('/payment-requests'), api.get('/approvals'), api.get('/payment-settlements'),
    ])
    requests.value = r.data.items
    approvals.value = a.data.items
    settlements.value = s.data.items
  } catch (e: any) { msg.error(errMsg(e)) }
}
onMounted(async () => {
  refresh()
  try {
    const [pj, inv] = await Promise.all([api.get('/projects'), api.get('/invoices', { params: { direction: 'PAYABLE' } })])
    projects.value = (pj.data.items || []).map((x: any) => ({ label: x.name, value: x.id }))
    invoices.value = (inv.data.items || []).map((x: any) => ({
      label: `${x.invoice_no || x.id.slice(0, 8)}（${money(x.amount)}）`, value: x.id, amount: Number(x.amount),
    }))
  } catch { /* 备选为空不阻断 */ }
})

// ---- 新增付款申请 ----
const showCreate = ref(false)
const createForm = reactive({ project_id: null as string | null, amount: null as number | null, prepayment_offset: 0, reason: '' })
async function submitCreate() {
  if (!createForm.project_id || !createForm.amount) { msg.warning('请选择项目并填写金额'); return }
  try {
    await api.post('/payment-requests', { ...createForm, reason: createForm.reason || null })
    showCreate.value = false; msg.success('付款申请已提交，待审批')
    Object.assign(createForm, { project_id: null, amount: null, prepayment_offset: 0, reason: '' })
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 审批 ----
async function doApprove(row: any) {
  try {
    await api.post(`/approvals/${row.id}/approve`)
    msg.success('已通过'); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}
const rejectTarget = ref<any | null>(null)
const rejectReason = ref('')
async function doReject() {
  if (!rejectReason.value.trim()) { msg.warning('驳回必须填原因'); return }
  try {
    await api.post(`/approvals/${rejectTarget.value.id}/reject`, { reason: rejectReason.value })
    rejectTarget.value = null; rejectReason.value = ''
    msg.success('已驳回'); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 登记付款 ----
const disburseTarget = ref<any | null>(null)
const disburseForm = reactive({
  transaction_date: '', settlement_rate: null as number | null,
  // 四期 W4：按资金池拆分支付（金租/银行/自有各出多少；Σ 须等于实付现金）
  split: false,
  splitLeasing: null as number | null, splitBank: null as number | null, splitOwn: null as number | null,
})
/** 实付现金 = 申请额 − 预付款冲抵 */
const cashOf = (r: any) => Number(r.amount) - Number(r.prepayment_offset || 0)
const splitSum = computed(() =>
  (disburseForm.splitLeasing || 0) + (disburseForm.splitBank || 0) + (disburseForm.splitOwn || 0))
const splitMismatch = computed(() =>
  !!(disburseForm.split && disburseTarget.value && splitSum.value !== cashOf(disburseTarget.value)))
async function doDisburse() {
  if (!disburseForm.transaction_date) { msg.warning('请选择付款日期'); return }
  if (splitMismatch.value) {
    msg.warning(`拆分合计 ${money(splitSum.value)} 须等于实付现金 ${money(cashOf(disburseTarget.value))}`)
    return
  }
  try {
    const payload: any = {
      transaction_date: disburseForm.transaction_date,
      settlement_rate: disburseForm.settlement_rate,
    }
    if (disburseForm.split) {
      const splits = [
        { pool: 'LEASING', amount: disburseForm.splitLeasing },
        { pool: 'BANK', amount: disburseForm.splitBank },
        { pool: 'OWN', amount: disburseForm.splitOwn },
      ].filter((s) => s.amount && s.amount > 0)
      if (!splits.length) { msg.warning('拆分支付至少填一个池的金额'); return }
      payload.pool_splits = splits
    }
    await api.post(`/payment-requests/${disburseTarget.value.id}/disburse`, payload)
    disburseTarget.value = null
    Object.assign(disburseForm, {
      transaction_date: '', settlement_rate: null,
      split: false, splitLeasing: null, splitBank: null, splitOwn: null,
    })
    msg.success('已登记付款（落资金流水）'); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 核销（多对多：动态行 发票+金额） ----
const settleTarget = ref<any | null>(null)
const settleRows = ref<{ invoice_id: string | null; amount: number | null }[]>([])
function openSettle(row: any) {
  settleTarget.value = row
  settleRows.value = [{ invoice_id: null, amount: null }]
}
async function doSettle() {
  const allocs = settleRows.value.filter((r) => r.amount)
  if (!allocs.length) { msg.warning('至少填一行核销明细'); return }
  try {
    await api.post('/payment-settlements', {
      txn_id: settleTarget.value.capital_transaction_id,
      allocations: allocs,
    })
    settleTarget.value = null
    msg.success('核销完成'); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

const reqStatusType = (s: string) => ({ 已批准: 'info', 已付款: 'success', 已驳回: 'error', 待审批: 'warning' }[s] || 'default')
const apprStatusType = (s: string) => ({ 已通过: 'success', 已驳回: 'error', 待审批: 'warning' }[s] || 'default')
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3>付款管控</h3>
      <n-button type="primary" size="small" @click="showCreate = true">新增付款申请</n-button>
    </div>

    <n-card title="审批中心" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 8 }"
        :columns="[
          { title: '类型', key: 'biz_type', width: 100 },
          { title: '标题', key: 'title' },
          { title: '状态', key: 'status', width: 100 },
          { title: '驳回原因', key: 'reject_reason', render: (r: any) => r.reject_reason || '—' },
          { title: '操作', key: '__op', width: 150 },
        ]"
        :data="approvals">
        <template #empty>暂无审批单</template>
      </n-data-table>
      <!-- 操作列用行渲染太绕，待审批的操作放下面列表 -->
      <n-space style="margin-top:8px" wrap>
        <n-tag v-for="a in approvals.filter((x: any) => x.status === '待审批')" :key="a.id" size="medium" :bordered="false" type="warning">
          {{ a.title }}
          <n-button size="tiny" type="success" style="margin-left:6px" @click="doApprove(a)">通过</n-button>
          <n-button size="tiny" type="error" style="margin-left:4px" @click="rejectTarget = a">驳回</n-button>
        </n-tag>
      </n-space>
    </n-card>

    <n-card title="付款申请" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 8 }"
        :columns="[
          { title: '金额', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
          { title: '预付款冲抵', key: 'prepayment_offset', align: 'right' as const, render: (r: any) => money(r.prepayment_offset) },
          { title: '状态', key: 'status', width: 100 },
          { title: '事由', key: 'reason', render: (r: any) => r.reason || '—' },
          { title: '操作', key: '__op', width: 190 },
        ]"
        :data="requests">
        <template #empty>暂无付款申请</template>
      </n-data-table>
      <n-space style="margin-top:8px" wrap>
        <n-tag v-for="r in requests.filter((x: any) => x.status === '已批准')" :key="r.id" :bordered="false" type="info">
          申请 {{ money(r.amount) }}
          <n-button size="tiny" type="primary" style="margin-left:6px" @click="disburseTarget = r">登记付款</n-button>
        </n-tag>
        <n-tag v-for="r in requests.filter((x: any) => x.status === '已付款')" :key="`s-${r.id}`" :bordered="false" type="success">
          已付 {{ money(r.amount) }}
          <n-button size="tiny" style="margin-left:6px" @click="openSettle(r)">核销</n-button>
        </n-tag>
      </n-space>
    </n-card>

    <n-card title="核销记录（多对多：一笔流水 ↔ 多发票/多设备）" size="small">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 8 }"
        :columns="[
          { title: '流水', key: 'capital_transaction_id', render: (r: any) => String(r.capital_transaction_id).slice(0, 8) + '…' },
          { title: '发票', key: 'invoice_id', render: (r: any) => (r.invoice_id ? String(r.invoice_id).slice(0, 8) + '…' : '待认领') },
          { title: '设备', key: 'device_id', render: (r: any) => (r.device_id ? String(r.device_id).slice(0, 8) + '…' : '—') },
          { title: '金额', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
        ]"
        :data="settlements">
        <template #empty>暂无核销记录</template>
      </n-data-table>
    </n-card>

    <!-- 新增付款申请 -->
    <n-modal v-model:show="showCreate" preset="card" title="新增付款申请" style="width:420px">
      <n-form label-placement="left" :label-width="110">
        <n-form-item label="项目" required><n-select v-model:value="createForm.project_id" :options="projects" filterable placeholder="选择项目" /></n-form-item>
        <n-form-item label="金额(元)" required><n-input-number v-model:value="createForm.amount" :min="0" style="width:100%" /></n-form-item>
        <n-form-item label="预付款冲抵"><n-input-number v-model:value="createForm.prepayment_offset" :min="0" style="width:100%" placeholder="用项目设备剩余预付款抵扣" /></n-form-item>
        <n-form-item label="事由"><n-input v-model:value="createForm.reason" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showCreate = false">取消</n-button><n-button type="primary" @click="submitCreate">提交审批</n-button></n-space></template>
    </n-modal>

    <!-- 驳回 -->
    <n-modal :show="rejectTarget !== null" preset="card" title="驳回审批" style="width:360px" @update:show="(v: boolean) => !v && (rejectTarget = null)">
      <n-input v-model:value="rejectReason" placeholder="驳回原因（必填）" />
      <template #footer><n-space justify="end"><n-button @click="rejectTarget = null">取消</n-button><n-button type="error" @click="doReject">驳回</n-button></n-space></template>
    </n-modal>

    <!-- 登记付款 -->
    <n-modal :show="disburseTarget !== null" preset="card" title="登记付款" style="width:440px" @update:show="(v: boolean) => !v && (disburseTarget = null)">
      <n-form label-placement="left" :label-width="110">
        <n-form-item label="付款日期" required>
          <n-date-picker type="date" style="width:100%" :value="ymdToTs(disburseForm.transaction_date)" @update:value="(ts: number | null) => disburseForm.transaction_date = tsToYmd(ts)" />
        </n-form-item>
        <n-form-item label="结算汇率"><n-input-number v-model:value="disburseForm.settlement_rate" :min="0" :precision="8" style="width:100%" placeholder="外币付款才填" /></n-form-item>
        <n-form-item label="拆分支付">
          <n-checkbox v-model:checked="disburseForm.split">按资金池拆分（金租/银行/自有各出多少）</n-checkbox>
        </n-form-item>
        <template v-if="disburseForm.split">
          <n-form-item label="金租池出"><n-input-number v-model:value="disburseForm.splitLeasing" :min="0" style="width:100%" placeholder="金租池支付额" /></n-form-item>
          <n-form-item label="银行池出"><n-input-number v-model:value="disburseForm.splitBank" :min="0" style="width:100%" placeholder="银行池支付额" /></n-form-item>
          <n-form-item label="自有池出"><n-input-number v-model:value="disburseForm.splitOwn" :min="0" style="width:100%" placeholder="自有池支付额" /></n-form-item>
          <div class="muted tiny" style="margin:-4px 0 8px 110px">
            实付现金 {{ money(cashOf(disburseTarget)) }}（申请额 − 冲抵）· 拆分合计 {{ money(splitSum) }}
            <span v-if="splitMismatch" style="color:#D97706">合计须等于实付现金</span>
          </div>
        </template>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="disburseTarget = null">取消</n-button><n-button type="primary" :disabled="splitMismatch" @click="doDisburse">登记</n-button></n-space></template>
    </n-modal>

    <!-- 核销 -->
    <n-modal :show="settleTarget !== null" preset="card" title="核销（可多行）" style="width:520px" @update:show="(v: boolean) => !v && (settleTarget = null)">
      <div v-for="(r, i) in settleRows" :key="i" class="alloc-row" style="display:flex;gap:8px;margin-bottom:8px">
        <n-select v-model:value="r.invoice_id" :options="invoices" filterable clearable placeholder="采购发票（空=待认领）" style="flex:1" />
        <n-input-number v-model:value="r.amount" :min="0" placeholder="金额" style="width:150px" />
        <n-button size="small" quaternary @click="settleRows.splice(i, 1)">删</n-button>
      </div>
      <n-button size="small" dashed @click="settleRows.push({ invoice_id: null, amount: null })">+ 加一行</n-button>
      <template #footer><n-space justify="end"><n-button @click="settleTarget = null">取消</n-button><n-button type="primary" @click="doSettle">核销</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<style scoped>
.muted { color: #94A3B8; }
.tiny { font-size: 12px; }
</style>
