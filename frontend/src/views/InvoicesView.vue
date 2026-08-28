<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCard, NDataTable, NDatePicker, NFormItem, NInput, NInputNumber, NModal,
  NPopconfirm, NProgress, NSelect, NSpace, NTabPane, NTabs, NTag, NTooltip, NUpload, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { money, tsToYmd, ymdToTs } from '../utils/format'
import { errMsg } from '../utils/errMsg'
import EmptyState from '../components/EmptyState.vue'

const msg = useMessage()
const route = useRoute()
const invoices = ref<any[]>([])
const contracts = ref<any[]>([])
const recon = ref<any[]>([])

// 工作台跳转带 ?project_id= 时，合同下拉只列该项目合同（预填消费）
const queryProjectId = (route.query.project_id as string) || ''

// 创建表单（缺陷#19b：移除业务上不存在的「到期日」字段）
const showCreate = ref(false)
const form = ref({
  contract_id: '' as string, amount: null as number | null,
  invoice_no: '', issue_date: '',
})

async function refresh() {
  try {
    const [inv, con, rec] = await Promise.all([
      api.get('/invoices'), api.get('/contracts'), api.get('/invoices/reconciliation'),
    ])
    invoices.value = inv.data.items
    contracts.value = con.data.items
    recon.value = rec.data.items
  } catch { msg.error('加载失败') }
}
onMounted(refresh)

const contractOpts = () => contracts.value
  .filter((c: any) => !queryProjectId || c.project_id === queryProjectId)
  .map((c: any) => ({
    label: `${c.contract_no} (${c.type === 'SALES' ? '销售' : '采购'})`, value: c.id,
  }))
const contractNo = (id: string) =>
  contracts.value.find((c: any) => c.id === id)?.contract_no || id.slice(0, 8) + '…'

// OCR 识别
function onOcrFinish({ event }: any) {
  try {
    const r = JSON.parse(event?.target?.response || '{}')
    if (r.error) { msg.warning(`OCR 识别失败: ${r.error}`); return }
    if (r.invoice_no) form.value.invoice_no = r.invoice_no
    if (r.amount) form.value.amount = r.amount
    if (r.issue_date) form.value.issue_date = r.issue_date
    const fields = [
      r.invoice_no ? '发票号' : '', r.amount ? '金额' : '', r.issue_date ? '日期' : '',
    ].filter(Boolean).join('/')
    msg.success(`OCR 识别成功（${fields || '未识别到关键字段，请手填'}）`)
  } catch { msg.error('OCR 解析失败') }
}
const ocrHeaders = { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }

async function createInvoice() {
  if (!form.value.contract_id || !form.value.amount) { msg.warning('请选合同 + 填金额'); return }
  try {
    await api.post('/invoices', { ...form.value, issue_date: form.value.issue_date || null })
    msg.success('发票已创建'); showCreate.value = false; await refresh()
    form.value = { contract_id: '', amount: null, invoice_no: '', issue_date: '' }
  } catch (e: any) { msg.error(errMsg(e)) }
}

// 收款/付款：弹窗选日期（默认今天，可补录历史日期）
const payTarget = ref<any | null>(null)
const payDateTs = ref<number>(Date.now())
function openPay(row: any) { payTarget.value = row; payDateTs.value = Date.now() }
async function submitPay() {
  if (!payTarget.value) return
  if (!payDateTs.value) { msg.warning('请选择日期'); return }
  try {
    await api.post(`/invoices/${payTarget.value.id}/pay`, { paid_date: tsToYmd(payDateTs.value) })
    msg.success('已标记收款/付款'); payTarget.value = null; await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

async function reverseInvoice(row: any) {
  try {
    await api.post(`/invoices/${row.id}/reverse`)
    msg.success('已红冲'); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// F4：实时生成发票/账单 PDF（不落库，浏览器直接下载）。
async function downloadPdf(row: any) {
  try {
    const resp = await api.get(`/invoices/${row.id}/pdf`, { responseType: 'blob' })
    const url = URL.createObjectURL(resp.data as unknown as Blob)
    const a = document.createElement('a')
    a.href = url; a.download = `发票-${row.invoice_no || row.id}.pdf`; a.click()
    URL.revokeObjectURL(url)
    msg.success('PDF 已生成')
  } catch (e: any) { msg.error(errMsg(e)) }
}

// 核销：选该项目入金流水，支持部分核销（分多笔，累计达发票金额自动「已核销」）
const recTarget = ref<any | null>(null)
const recTxns = ref<any[]>([])
const recTxnId = ref<string | null>(null)
const recLoading = ref(false)
const recMatched = ref(0) // 该发票已核销累计金额（InvoiceOut.matched_amount）
async function loadRecTxns() {
  if (!recTarget.value) return
  const contract = contracts.value.find((c: any) => c.id === recTarget.value.contract_id)
  recLoading.value = true
  try {
    const { data } = await api.get('/capital/transactions', {
      params: { project_id: contract?.project_id, direction: 'IN' },
    })
    recTxns.value = (data.items || []).filter((t: any) => !t.is_reversal)
  } catch (e: any) { msg.error(errMsg(e)); recTxns.value = [] }
  finally { recLoading.value = false }
}
async function openReconcile(row: any) {
  recTarget.value = row; recTxnId.value = null
  // 行对象一般已带 matched_amount（列表接口返回 InvoiceOut）；缺失时从列表接口补取
  if (row.matched_amount !== undefined && row.matched_amount !== null) {
    recMatched.value = Number(row.matched_amount)
  } else {
    recMatched.value = 0
    try {
      const { data } = await api.get('/invoices')
      const found = (data.items || []).find((i: any) => i.id === row.id)
      if (found) recMatched.value = Number(found.matched_amount || 0)
    } catch { /* 取不到就按 0 展示，核销响应会带回准确值 */ }
  }
  await loadRecTxns()
}
async function submitReconcile() {
  if (!recTarget.value || !recTxnId.value) { msg.warning('请选择资金流水'); return }
  try {
    const { data } = await api.post(`/invoices/${recTarget.value.id}/reconcile/${recTxnId.value}`)
    recMatched.value = Number(data.matched_amount ?? recMatched.value)
    if (data.status === '已核销') {
      msg.success('已全部核销'); recTarget.value = null; await refresh()
    } else {
      msg.success('核销成功（部分核销，可继续选下一笔）')
      recTxnId.value = null
      await loadRecTxns() // 重载流水列表，已核销进度保留
    }
  } catch (e: any) { msg.error(errMsg(e)) }
}

const invCols = [
  { title: '发票号', key: 'invoice_no', width: 130, render: (r: any) => r.invoice_no || '—' },
  { title: '方向', key: 'direction', width: 70, render: (r: any) =>
      h(NTag, { size: 'small', type: r.direction === 'RECEIVABLE' ? 'success' : 'warning', bordered: false },
        () => r.direction === 'RECEIVABLE' ? '应收' : '应付') },
  { title: '含税金额', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
  { title: '开票日', key: 'issue_date', width: 110, render: (r: any) => r.issue_date || '—' },
  { title: '状态', key: 'status', width: 80, render: (r: any) =>
      h(NTag, { size: 'small', bordered: false,
        type: r.status === '已红冲' ? 'error' : r.status === '已付款' || r.status === '已收票' || r.status === '已核销' ? 'success' : 'info' },
        () => r.status) },
  { title: '操作', key: '__op', width: 270, render: (r: any) =>
      h(NSpace, { size: 4 }, () => [
        r.status !== '已红冲'
          ? h(NTooltip, null, {
              trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => downloadPdf(r) }, () => 'PDF'),
              default: () => '导出 PDF：实时生成发票/账单，可直接打印或发送客户对账',
            })
          : null,
        r.status !== '已付款' && r.status !== '已收票' && r.status !== '已红冲'
          ? h(NButton, { size: 'tiny', type: 'primary', quaternary: true, onClick: () => openPay(r) }, () => '收款/付款')
          : null,
        r.status !== '已红冲' && r.status !== '已核销'
          ? h(NTooltip, null, {
              trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => openReconcile(r) }, () => '核销'),
              default: () => '核销：将发票与资金流水逐笔勾销，支持部分核销',
            })
          : null,
        r.status !== '已红冲'
          ? h(NPopconfirm, { onPositiveClick: () => reverseInvoice(r) }, {
              trigger: () => h(NTooltip, null, {
                trigger: () => h(NButton, { size: 'tiny', type: 'error', quaternary: true }, () => '红冲'),
                default: () => '红冲：作废错误发票，系统生成等额反向凭证留痕',
              }),
              default: () => '红冲将作废该发票并生成反向凭证，对账自动剔除，不可恢复。确认？',
            })
          : null,
      ]) },
]

const reconCols = [
  { title: '合同', key: 'contract_id', width: 140, render: (r: any) => contractNo(r.contract_id) },
  { title: '合同额(不含税)', key: 'contract_amount', align: 'right' as const, render: (r: any) => money(r.contract_amount) },
  { title: '应收(计费)', key: 'billed', align: 'right' as const, render: (r: any) => money(r.billed) },
  { title: '已开票', key: 'invoiced', align: 'right' as const, render: (r: any) => money(r.invoiced) },
  { title: '已收款', key: 'received', align: 'right' as const, render: (r: any) => money(r.received) },
  { title: '差额 合同-计费', key: 'gap_billed', align: 'right' as const, render: (r: any) => {
      const v = Number(r.gap_billed || 0); return Math.abs(v) < 0.005 ? '—' : h('span', { style: 'color:#EA580C;font-weight:600' }, money(v))
    } },
]
</script>

<template>
  <n-tabs type="line" animated>
    <!-- Tab 1: 发票列表 -->
    <n-tab-pane name="list" tab="发票列表">
      <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center">
        <h3>发票（{{ invoices.length }} 张）</h3>
        <n-button type="primary" @click="showCreate = true">新增发票</n-button>
      </div>
      <div class="card" style="padding:4px">
        <n-data-table :columns="invCols" :data="invoices" :bordered="false" size="small" striped>
          <template #empty>
            <EmptyState description="还没有发票，点击右上角「新增发票」，计费确认后即可按合同开具" />
          </template>
        </n-data-table>
      </div>

      <!-- 创建弹窗（含 OCR） -->
      <n-modal v-model:show="showCreate" preset="card" title="新增发票" style="width:480px;max-width:94vw">
        <n-space vertical :size="12">
          <!-- OCR 识别（缺陷#19a：仅图片；失败有明确提示） -->
          <n-upload
            action="/api/ocr/invoice"
            :headers="ocrHeaders"
            accept="image/*"
            :show-file-list="false"
            @finish="onOcrFinish"
            @error="() => { msg.error('OCR 识别失败：上传/服务异常（仅支持 JPG/PNG 图片）') }"
          >
            <n-button dashed block>📷 OCR 识别发票（上传图片自动填表）</n-button>
          </n-upload>
          <div class="muted tiny">支持拍照/扫描的增值税发票图片（JPG/PNG）。识别后请人工校验。</div>

          <n-form-item label="关联合同">
            <n-select v-model:value="form.contract_id" :options="contractOpts()" placeholder="选合同" filterable />
          </n-form-item>
          <n-form-item label="发票号">
            <n-input v-model:value="form.invoice_no" placeholder="OCR 自动填或手输" />
          </n-form-item>
          <n-form-item label="含税金额(元)">
            <n-input-number v-model:value="form.amount" :show-button="false" style="width:100%" placeholder="OCR 自动填或手输" />
          </n-form-item>
          <n-space>
            <n-form-item label="开票日期">
              <n-date-picker type="date" :value="ymdToTs(form.issue_date)"
                @update:value="(ts: number | null) => form.issue_date = tsToYmd(ts)" style="width:160px" />
            </n-form-item>
          </n-space>
        </n-space>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showCreate = false">取消</n-button>
            <n-button type="primary" @click="createInvoice">创建</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- 收款/付款日期弹窗 -->
      <n-modal :show="!!payTarget" preset="card" title="标记收款/付款" style="width:360px"
        @update:show="(v: boolean) => { if (!v) payTarget = null }">
        <n-form-item label="收付日期">
          <n-date-picker v-model:value="payDateTs" type="date" style="width:100%" />
        </n-form-item>
        <div class="muted tiny">默认今天；补录历史回款可选择过去的日期。</div>
        <template #footer>
          <n-space justify="end">
            <n-button @click="payTarget = null">取消</n-button>
            <n-button type="primary" @click="submitPay">确认</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- 核销弹窗 -->
      <n-modal :show="!!recTarget" preset="card" title="发票核销" style="width:440px;max-width:94vw"
        @update:show="(v: boolean) => { if (!v) { recTarget = null; refresh() } }">
        <n-space vertical :size="12">
          <div>
            已核销 <b class="num">{{ money(recMatched) }}</b> / 发票金额 <b class="num">{{ money(recTarget?.amount) }}</b>
            <n-progress type="line" :percentage="recTarget?.amount ? Math.min(100, Math.round(recMatched / Number(recTarget.amount) * 100)) : 0"
              :show-indicator="false" style="margin-top:6px" />
          </div>
          <div class="muted tiny">选择该项目的一笔入金流水进行勾销；支持部分核销——可分多笔逐笔核销，累计金额达到发票金额后自动变为「已核销」。</div>
          <n-form-item label="资金流水（入金）">
            <n-select v-model:value="recTxnId" :loading="recLoading" filterable
              :options="recTxns.map((t: any) => ({ label: `${t.transaction_date} · ${money(t.amount)} · ${t.note || t.source_type}`, value: t.id }))"
              placeholder="选择收款流水" />
          </n-form-item>
        </n-space>
        <template #footer>
          <n-space justify="end">
            <n-button @click="recTarget = null; refresh()">关闭</n-button>
            <n-button type="primary" :disabled="!recTxnId" @click="submitReconcile">核销</n-button>
          </n-space>
        </template>
      </n-modal>
    </n-tab-pane>

    <!-- Tab 2: 三流对账 -->
    <n-tab-pane name="recon" tab="三流对账">
      <n-card>
        <div class="muted tiny" style="margin-bottom:10px">合同额 → 应收(计费) → 已开票 → 已收款，逐级差异。</div>
        <n-data-table :columns="reconCols" :data="recon" :bordered="false" size="small" striped>
          <template #empty>
            <EmptyState description="暂无对账数据，开具发票并登记收付款后这里会自动汇总" />
          </template>
        </n-data-table>
      </n-card>
    </n-tab-pane>
  </n-tabs>
</template>

<style scoped>
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
