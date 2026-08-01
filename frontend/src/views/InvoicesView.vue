<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpace,
  NTabPane, NTabs, NTag, NUpload, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { money } from '../utils/format'

const msg = useMessage()
const invoices = ref<any[]>([])
const contracts = ref<any[]>([])
const recon = ref<any[]>([])

// 创建表单
const showCreate = ref(false)
const form = ref({
  contract_id: '' as string, amount: null as number | null,
  invoice_no: '', issue_date: '', due_date: '',
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

const contractOpts = () => contracts.value.map((c: any) => ({
  label: `${c.contract_no} (${c.type === 'SALES' ? '销售' : '采购'})`, value: c.id,
}))

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
    await api.post('/invoices', form.value)
    msg.success('发票已创建'); showCreate.value = false; await refresh()
    form.value = { contract_id: '', amount: null, invoice_no: '', issue_date: '', due_date: '' }
  } catch (e: any) {
    const det = e.response?.data?.detail
    msg.error(typeof det === 'string' ? det : det?.message || '创建失败')
  }
}

async function payInvoice(row: any) {
  const today = new Date().toISOString().slice(0, 10)
  try {
    await api.post(`/invoices/${row.id}/pay`, { paid_date: today })
    msg.success('已标记收款/付款'); await refresh()
  } catch (e: any) { msg.error(e.response?.data?.detail?.message || '操作失败') }
}

async function reverseInvoice(row: any) {
  try {
    await api.post(`/invoices/${row.id}/reverse`)
    msg.success('已红冲'); await refresh()
  } catch (e: any) { msg.error(e.response?.data?.detail?.message || '红冲失败') }
}

const invCols = [
  { title: '发票号', key: 'invoice_no', width: 130, render: (r: any) => r.invoice_no || '—' },
  { title: '方向', key: 'direction', width: 70, render: (r: any) =>
      h(NTag, { size: 'small', type: r.direction === 'RECEIVABLE' ? 'success' : 'warning', bordered: false },
        () => r.direction === 'RECEIVABLE' ? '应收' : '应付') },
  { title: '含税金额', key: 'amount', align: 'right', render: (r: any) => money(r.amount) },
  { title: '开票日', key: 'issue_date', width: 110, render: (r: any) => r.issue_date || '—' },
  { title: '状态', key: 'status', width: 80, render: (r: any) =>
      h(NTag, { size: 'small', bordered: false,
        type: r.status === '已红冲' ? 'error' : r.status === '已付款' || r.status === '已收票' ? 'success' : 'info' },
        () => r.status) },
  { title: '操作', key: '__op', width: 140, render: (r: any) =>
      h(NSpace, { size: 4 }, () => [
        r.status !== '已付款' && r.status !== '已收票' && r.status !== '已红冲'
          ? h(NButton, { size: 'tiny', type: 'primary', quaternary: true, onClick: () => payInvoice(r) }, () => '收款/付款')
          : null,
        r.status !== '已红冲'
          ? h(NButton, { size: 'tiny', type: 'error', quaternary: true, onClick: () => reverseInvoice(r) }, () => '红冲')
          : null,
      ]) },
]

const reconCols = [
  { title: '合同', key: 'contract_id', width: 100, render: (r: any) => r.contract_id.slice(0, 8) + '…' },
  { title: '合同额(不含税)', key: 'contract_amount', align: 'right', render: (r: any) => money(r.contract_amount) },
  { title: '应收(计费)', key: 'billed', align: 'right', render: (r: any) => money(r.billed) },
  { title: '已开票', key: 'invoiced', align: 'right', render: (r: any) => money(r.invoiced) },
  { title: '已收款', key: 'received', align: 'right', render: (r: any) => money(r.received) },
  { title: '差额 合同-计费', key: 'gap_billed', align: 'right', render: (r: any) => {
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
        <n-data-table :columns="invCols" :data="invoices" :bordered="false" size="small" striped />
      </div>

      <!-- 创建弹窗（含 OCR） -->
      <n-modal v-model:show="showCreate" preset="card" title="新增发票" style="width:480px;max-width:94vw">
        <n-space vertical :size="12">
          <!-- OCR 识别 -->
          <n-upload
            action="/api/ocr/invoice"
            :headers="ocrHeaders"
            accept="image/*,.pdf"
            :show-file-list="false"
            @finish="onOcrFinish"
          >
            <n-button dashed block>📷 OCR 识别发票（上传图片/PDF 自动填表）</n-button>
          </n-upload>
          <div class="muted tiny">支持拍照/扫描的增值税发票图片（JPG/PNG/PDF）。识别后请人工校验。</div>

          <n-form-item label="关联合同">
            <n-select v-model:value="form.contract_id" :options="contractOpts()" placeholder="选合同" filterable />
          </n-form-item>
          <n-form-item label="发票号">
            <n-input v-model:value="form.invoice_no" placeholder="OCR 自动填或手输" />
          </n-form-item>
          <n-form-item label="含税金额">
            <n-input-number v-model:value="form.amount" :show-button="false" style="width:100%" placeholder="OCR 自动填或手输" />
          </n-form-item>
          <n-space>
            <n-form-item label="开票日期"><n-input v-model:value="form.issue_date" placeholder="YYYY-MM-DD" /></n-form-item>
            <n-form-item label="到期日"><n-input v-model:value="form.due_date" placeholder="YYYY-MM-DD" /></n-form-item>
          </n-space>
        </n-space>
        <template #footer>
          <n-space justify="end">
            <n-button @click="showCreate = false">取消</n-button>
            <n-button type="primary" @click="createInvoice">创建</n-button>
          </n-space>
        </template>
      </n-modal>
    </n-tab-pane>

    <!-- Tab 2: 三流对账 -->
    <n-tab-pane name="recon" tab="三流对账">
      <n-card>
        <div class="muted tiny" style="margin-bottom:10px">合同额 → 应收(计费) → 已开票 → 已收款，逐级差异。</div>
        <n-data-table :columns="reconCols" :data="recon" :bordered="false" size="small" striped />
      </n-card>
    </n-tab-pane>
  </n-tabs>
</template>

<style scoped>
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
