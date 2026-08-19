<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCard, NDataTable, NDatePicker, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpace, NTag,
  useDialog, useMessage,
} from 'naive-ui'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'
import EmptyState from '../components/EmptyState.vue'

interface Device {
  id: string; sn: string; project_id: string; order_id: string | null
  batch_id: string | null; sales_contract_id: string | null
  equipment_model_id: string; supplier_id: string | null
  monthly_price: string | null; config: Record<string, any> | null
  leasing_mode: string | null; purchase_value: string | null
  prepayment_amount: string; status: string; ownership: string | null
  prepayment_settled: boolean
}

const STATUS_OPTIONS = ['订货', '在途', '到货', '己方压测', '上架', '客户压测', '点亮验收']
  .map((s) => ({ label: s, value: s }))
const STAGE_STATUS_OPTIONS = ['未开始', '进行中', '已完成', '不合格'].map((s) => ({ label: s, value: s }))
const LEASING_OPTIONS = ['自有', '直租', '售后回租'].map((s) => ({ label: s, value: s }))
const OWNERSHIP_OPTIONS = ['表内自有', '金租表外', '转售表外'].map((s) => ({ label: s, value: s }))

const STATUS_TAG: Record<string, 'default' | 'info' | 'warning' | 'success'> = {
  订货: 'default', 在途: 'info', 到货: 'info', 己方压测: 'warning',
  上架: 'warning', 客户压测: 'warning', 点亮验收: 'success',
}

const msg = useMessage()
const dialog = useDialog()
const route = useRoute()
const items = ref<Device[]>([])
const loading = ref(false)

// 下拉数据源
const projects = ref<any[]>([])
const orders = ref<any[]>([])
const salesOrders = ref<any[]>([])
const equipModels = ref<any[]>([])
const suppliers = ref<any[]>([])

// F2 可租库存看板（按型号聚合表内自营设备）
const inventory = ref<any[]>([])
const invTotals = computed(() => inventory.value.reduce((acc: any, r: any) => ({
  available: acc.available + (r.available || 0),
  rented: acc.rented + (r.rented || 0),
  pending: acc.pending + (r.pending || 0),
}), { available: 0, rented: 0, pending: 0 }))

// 筛选（型号/金租模式后端暂不支持，前端过滤）
// 步骤导航实体级跳转：?project_id=<pid> 时初始化项目筛选（fProject 走服务端过滤，见 load()）。
const fProject = ref<string | null>((route.query.project_id as string) || null)
const fBatch = ref<string | null>(null)
const fModel = ref<string | null>(null)
const fStatus = ref<string | null>(null)
const fLeasingMode = ref<string | null>(null)

const projectOpts = () => projects.value.map((p: any) => ({ label: p.name, value: p.id }))
const orderOpts = () => orders.value.map((o: any) => ({
  label: `${projectName(o.project_id)} · ${o.quantity ?? '?'}台 · ${o.status} (${o.id.slice(0, 8)})`, value: o.id,
}))
const equipOpts = () => equipModels.value.map((m: any) => ({
  label: `${m.name}${m.gpu_type ? ` · ${m.gpu_type}x${m.gpu_count}` : ''}`, value: m.id,
}))
const supplierOpts = () => suppliers.value.map((s: any) => ({ label: s.name, value: s.id }))

const projectName = (id: string) => projects.value.find((p: any) => p.id === id)?.name || id.slice(0, 8) + '…'
const equipName = (id: string) => equipModels.value.find((m: any) => m.id === id)?.name || id.slice(0, 8) + '…'
const batchLabel = (id: string | null) => {
  if (!id) return '-'
  const o = orders.value.find((x: any) => x.id === id)
  return o ? `${o.id.slice(0, 8)} (${o.quantity ?? '?'}台)` : id.slice(0, 8) + '…'
}
const fmtMoney = (v: string | null) => (v == null ? '-' : Number(v).toLocaleString())

const filteredItems = computed(() => items.value.filter((d) => {
  if (fModel.value && d.equipment_model_id !== fModel.value) return false
  if (fLeasingMode.value && d.leasing_mode !== fLeasingMode.value) return false
  return true
}))

async function load() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (fProject.value) params.project_id = fProject.value
    if (fBatch.value) params.batch_id = fBatch.value
    if (fStatus.value) params.status = fStatus.value
    const [dev, proj, ord, so, eq, sup, inv] = await Promise.all([
      http.get('/devices', { params }),
      http.get('/projects'), http.get('/orders'), http.get('/sales-orders'),
      http.get('/equipment-models'), http.get('/suppliers'),
      http.get('/devices/inventory-summary'),
    ])
    items.value = dev.data.items
    projects.value = proj.data.items
    orders.value = ord.data.items
    salesOrders.value = so.data
    equipModels.value = eq.data.items
    suppliers.value = sup.data.items
    inventory.value = inv.data.items || []
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}

// ---- 新增 / 编辑 ----
const showEdit = ref(false)
const editingId = ref<string | null>(null)
const form = ref({
  sn: '', project_id: '' as string, equipment_model_id: '' as string,
  order_id: null as string | null, supplier_id: null as string | null,
  monthly_price: null as number | null, purchase_value: null as number | null,
  prepayment_amount: null as number | null,
  leasing_mode: null as string | null, ownership: null as string | null,
})

function openCreate() {
  editingId.value = null
  form.value = {
    sn: '', project_id: '', equipment_model_id: '', order_id: null, supplier_id: null,
    monthly_price: null, purchase_value: null, prepayment_amount: null,
    leasing_mode: null, ownership: null,
  }
  showEdit.value = true
}

function openEdit(r: Device) {
  editingId.value = r.id
  form.value = {
    sn: r.sn, project_id: r.project_id, equipment_model_id: r.equipment_model_id,
    order_id: r.order_id, supplier_id: r.supplier_id,
    monthly_price: r.monthly_price == null ? null : Number(r.monthly_price),
    purchase_value: r.purchase_value == null ? null : Number(r.purchase_value),
    prepayment_amount: r.prepayment_amount == null ? null : Number(r.prepayment_amount),
    leasing_mode: r.leasing_mode, ownership: r.ownership,
  }
  showEdit.value = true
}

async function submitEdit() {
  const f = form.value
  try {
    if (editingId.value) {
      // 编辑白名单：status 归状态机、batch 走批次操作，均不在此提交
      await http.patch(`/devices/${editingId.value}`, {
        sn: f.sn || undefined, order_id: f.order_id, supplier_id: f.supplier_id,
        monthly_price: f.monthly_price, purchase_value: f.purchase_value,
        prepayment_amount: f.prepayment_amount, leasing_mode: f.leasing_mode, ownership: f.ownership,
      })
      msg.success('设备已更新')
    } else {
      if (!f.project_id || !f.equipment_model_id) { msg.warning('请选择项目和设备型号'); return }
      // M-2：status 归设备状态机唯一入口（后端恒为"订货"），此处不再提交
      await http.post('/devices', {
        sn: f.sn || null, project_id: f.project_id, equipment_model_id: f.equipment_model_id,
        order_id: f.order_id, supplier_id: f.supplier_id,
        monthly_price: f.monthly_price, purchase_value: f.purchase_value,
        prepayment_amount: f.prepayment_amount ?? 0,
        leasing_mode: f.leasing_mode, ownership: f.ownership,
      })
      msg.success('设备已创建')
    }
    showEdit.value = false
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

function removeDevice(r: Device) {
  dialog.warning({
    title: '删除设备',
    content: `确认删除设备 ${r.sn}？删除后不可撤销，已关联的计费/资产数据可能受影响。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await http.delete(`/devices/${r.id}`)
        msg.success('已删除')
        await load()
      } catch (e: any) { msg.error(errMsg(e)) }
    },
  })
}

// ---- 批次组合 / 移出 ----
const checkedRowKeys = ref<string[]>([])
const showBatchAssign = ref(false)
const batchTarget = ref<string | null>(null)

async function submitBatchAssign() {
  if (!batchTarget.value) { msg.warning('请选择批次订单'); return }
  let ok = 0
  let fail = 0
  for (const id of checkedRowKeys.value) {
    try {
      await http.post('/devices/batch-assign', { device_id: id, batch_id: batchTarget.value })
      ok += 1
    } catch { fail += 1 }
  }
  if (fail) msg.warning(`批次组合完成：成功 ${ok} 台，失败 ${fail} 台（可能已在批次中）`)
  else msg.success(`批次组合完成：${ok} 台已挂入批次`)
  showBatchAssign.value = false
  checkedRowKeys.value = []
  await load()
}

async function removeFromBatch(r: Device) {
  try {
    await http.post('/devices/batch-remove', { device_id: r.id })
    msg.success(`设备 ${r.sn} 已移出批次`)
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- W4：销售批次组合（照采购批次组合模式）----
const showSalesBatchAssign = ref(false)
const salesBatchTarget = ref<string | null>(null)
const salesBatchOpts = () => salesOrders.value
  .filter((s: any) => s.is_batch)
  .map((s: any) => ({ label: `${s.batch_name || s.id.slice(0, 8)} · ${s.quantity}台`, value: s.id }))

async function submitSalesBatchAssign() {
  if (!salesBatchTarget.value) { msg.warning('请选择销售批次'); return }
  let ok = 0
  let fail = 0
  for (const id of checkedRowKeys.value) {
    try {
      await http.post('/sales-orders/batch-assign', { device_id: id, sales_batch_id: salesBatchTarget.value })
      ok += 1
    } catch { fail += 1 }
  }
  if (fail) msg.warning(`销售批次组合完成：成功 ${ok} 台，失败 ${fail} 台（可能已在销售批次中）`)
  else msg.success(`销售批次组合完成：${ok} 台已挂入销售批次`)
  showSalesBatchAssign.value = false
  checkedRowKeys.value = []
  await load()
}

// ---- 节点推进（单台 / 批量）----
const showAdvance = ref(false)
const advanceTargetIds = ref<string[]>([])
const advanceTargetLabel = ref('')
const advStage = ref<string | null>(null)
const advStatus = ref<string | null>(null)
const advDate = ref<number | null>(null)

function fmtDate(ts: number | null): string | undefined {
  if (ts == null) return undefined
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function openAdvanceBatch() {
  advanceTargetIds.value = [...checkedRowKeys.value]
  advanceTargetLabel.value = `选中的 ${checkedRowKeys.value.length} 台设备`
  advStage.value = null; advStatus.value = null; advDate.value = null
  showAdvance.value = true
}

function openAdvanceOne(r: Device) {
  advanceTargetIds.value = [r.id]
  advanceTargetLabel.value = `设备 ${r.sn}`
  advStage.value = null; advStatus.value = null; advDate.value = null
  showAdvance.value = true
}

async function submitAdvance() {
  if (!advStage.value || !advStatus.value) { msg.warning('请选择节点和状态'); return }
  let ok = 0; let fail = 0
  for (const id of advanceTargetIds.value) {
    try {
      await http.post(`/devices/${id}/stage`, {
        stage: advStage.value, status: advStatus.value, actual_date: fmtDate(advDate.value),
      })
      ok += 1
    } catch { fail += 1 }
  }
  if (fail) msg.warning(`节点推进完成：成功 ${ok} 台，失败 ${fail} 台（可能状态机不允许该转换）`)
  else msg.success(`节点推进完成：${ok} 台`)
  showAdvance.value = false
  checkedRowKeys.value = []
  await load()
}

// ---- 回租出售（售后回租专属，W7-8）----
const showLeaseback = ref(false)
const leasebackTarget = ref<Device | null>(null)
const leasebackForm = ref({
  sale_date: null as number | null,
  leasing_org_id: null as string | null,
  sale_price: null as number | null,
  leasing_process_id: null as string | null,
  note: null as string | null,
})
const leasingProcesses = ref<any[]>([])

const funderOpts = computed(() =>
  suppliers.value.filter((s: any) => s.type === '资金供应商')
    .map((s: any) => ({ label: s.name, value: s.id })))
const processOpts = () => leasingProcesses.value.map((p: any) => ({
  label: `${p.status} · ${Number(p.total_amount).toLocaleString()} (${p.id.slice(0, 8)})`, value: p.id,
}))

async function openLeaseback(r: Device) {
  leasebackTarget.value = r
  leasebackForm.value = {
    sale_date: Date.now(), leasing_org_id: null,              // 出售日预填今日（合理默认；e2e 免日历交互）
    sale_price: r.purchase_value == null ? null : Number(r.purchase_value),  // 预填采购原值作起点
    leasing_process_id: null, note: null,
  }
  try {
    const { data } = await http.get('/leasing/processes', { params: { project_id: r.project_id } })
    leasingProcesses.value = data.items
  } catch { leasingProcesses.value = [] }
  showLeaseback.value = true
}

async function submitLeaseback() {
  const r = leasebackTarget.value
  if (!r) return
  const f = leasebackForm.value
  if (!f.sale_date || !f.leasing_org_id || f.sale_price == null || !f.leasing_process_id) {
    msg.warning('请填写出售日 / 金租机构 / 出售价 / 关联融资申请'); return
  }
  try {
    const { data } = await http.post(`/devices/${r.id}/leaseback-sale`, {
      sale_date: fmtDate(f.sale_date),
      leasing_org_id: f.leasing_org_id,
      sale_price: f.sale_price,
      leasing_process_id: f.leasing_process_id,
      note: f.note || undefined,
    })
    msg.success(`回租出售完成：账面 ${Number(data.carrying_amount).toLocaleString()}，出售损益 ${Number(data.sale_gain_loss).toLocaleString()}`)
    showLeaseback.value = false
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- Excel 导入 ----
const showImport = ref(false)
const importForm = ref({ project_id: '' as string, equipment_model_id: '' as string })
const importFile = ref<File | null>(null)

function onFileChange(e: Event) {
  importFile.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

async function submitImport() {
  if (!importForm.value.project_id || !importForm.value.equipment_model_id) { msg.warning('请选择项目和设备型号'); return }
  if (!importFile.value) { msg.warning('请选择 Excel 文件'); return }
  const fd = new FormData()
  fd.append('file', importFile.value)
  try {
    const { data } = await http.post('/devices/import', fd, {
      params: { project_id: importForm.value.project_id, equipment_model_id: importForm.value.equipment_model_id },
    })
    msg.success(`导入完成：${data.imported} 台设备`)
    showImport.value = false
    importFile.value = null
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

const columns = [
  { type: 'selection' as const },
  { title: 'SN', key: 'sn', width: 170 },
  { title: '型号', key: 'equipment_model_id', render: (r: Device) => equipName(r.equipment_model_id) },
  { title: '项目', key: 'project_id', render: (r: Device) => projectName(r.project_id) },
  { title: '批次', key: 'batch_id', width: 140, render: (r: Device) => batchLabel(r.batch_id) },
  {
    title: '状态', key: 'status', width: 100,
    render: (r: Device) => h(NTag, { type: STATUS_TAG[r.status] ?? 'default', size: 'small' }, () => r.status),
  },
  { title: '金租模式', key: 'leasing_mode', width: 100, render: (r: Device) => r.leasing_mode ?? '-' },
  { title: '权属', key: 'ownership', width: 100, render: (r: Device) => r.ownership ?? '-' },
  { title: '采购原值', key: 'purchase_value', align: 'right' as const, render: (r: Device) => fmtMoney(r.purchase_value) },
  { title: '月计费额', key: 'monthly_price', align: 'right' as const, render: (r: Device) => fmtMoney(r.monthly_price) },
  { title: '预付款', key: 'prepayment_amount', align: 'right' as const, render: (r: Device) => fmtMoney(r.prepayment_amount) },
  {
    title: '操作', key: 'actions', width: 320,
    render: (r: Device) => h(NSpace, { size: 4 }, () => [
      h(NButton, { size: 'tiny', onClick: () => openEdit(r) }, () => '编辑'),
      h(NButton, { size: 'tiny', tertiary: true, type: 'info', onClick: () => openAdvanceOne(r) }, () => '推进'),
      r.leasing_mode === '售后回租'
        ? (r.prepayment_settled
            ? h(NTag, { size: 'small', type: 'warning' }, () => '已出售')
            : h(NButton, { size: 'tiny', tertiary: true, type: 'warning', onClick: () => openLeaseback(r) }, () => '回租出售'))
        : null,
      r.batch_id
        ? h(NButton, { size: 'tiny', tertiary: true, onClick: () => removeFromBatch(r) }, () => '移出批次')
        : null,
      h(NButton, { size: 'tiny', tertiary: true, type: 'error', onClick: () => removeDevice(r) }, () => '删除'),
    ]),
  },
]

// F2 可租库存看板列：可租数高亮（业务最关心「还能租出几台」）
const invCols = [
  { title: '型号', key: 'model_name' },
  { title: '类别', key: 'category', width: 90, render: (r: any) => r.category || '—' },
  { title: '可租', key: 'available', align: 'right' as const, width: 80, render: (r: any) =>
      r.available > 0 ? h('span', { style: 'color:#16A34A;font-weight:600' }, r.available) : '—' },
  { title: '在租', key: 'rented', align: 'right' as const, width: 80 },
  { title: '待交付', key: 'pending', align: 'right' as const, width: 80 },
  { title: '自营合计', key: 'total', align: 'right' as const, width: 90 },
]

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">设备清单</h2>
      <n-space>
        <n-button :disabled="!checkedRowKeys.length" @click="openAdvanceBatch">
          批量推进{{ checkedRowKeys.length ? ` (${checkedRowKeys.length})` : '' }}
        </n-button>
        <n-button :disabled="!checkedRowKeys.length" @click="batchTarget = null; showBatchAssign = true">
          批次组合{{ checkedRowKeys.length ? ` (${checkedRowKeys.length})` : '' }}
        </n-button>
        <n-button :disabled="!checkedRowKeys.length" @click="salesBatchTarget = null; showSalesBatchAssign = true">
          销售批次组合{{ checkedRowKeys.length ? ` (${checkedRowKeys.length})` : '' }}
        </n-button>
        <n-button @click="showImport = true">Excel 导入</n-button>
        <n-button type="primary" @click="openCreate">新增设备</n-button>
      </n-space>
    </div>

    <n-card title="可租库存（表内自营设备）" size="small" style="margin-bottom:16px">
      <template #header-extra>
        <span class="muted tiny">按型号聚合 · 表外金租/转售不计入自营</span>
      </template>
      <div class="inv-totals">
        <div class="inv-total">
          <div class="inv-num green">{{ invTotals.available }}</div>
          <div class="inv-lbl">可租（随时下发）</div>
        </div>
        <div class="inv-total">
          <div class="inv-num blue">{{ invTotals.rented }}</div>
          <div class="inv-lbl">在租（计费中）</div>
        </div>
        <div class="inv-total">
          <div class="inv-num gray">{{ invTotals.pending }}</div>
          <div class="inv-lbl">待交付（未点亮）</div>
        </div>
      </div>
      <n-data-table v-if="inventory.length" :columns="invCols" :data="inventory"
        :bordered="false" size="small" striped style="margin-top:10px" />
    </n-card>

    <n-space style="margin-bottom:12px" :size="8">
      <n-select v-model:value="fProject" :options="projectOpts()" placeholder="项目" clearable filterable
        style="width:200px" @update:value="load" />
      <n-select v-model:value="fBatch" :options="orderOpts()" placeholder="批次" clearable filterable
        style="width:220px" @update:value="load" />
      <n-select v-model:value="fModel" :options="equipOpts()" placeholder="型号" clearable filterable
        style="width:180px" />
      <n-select v-model:value="fStatus" :options="STATUS_OPTIONS" placeholder="状态" clearable
        style="width:130px" @update:value="load" />
      <n-select v-model:value="fLeasingMode" :options="LEASING_OPTIONS" placeholder="金租模式" clearable
        style="width:120px" />
    </n-space>

    <n-dataTable
      class="device-list-table"
      v-model:checked-row-keys="checkedRowKeys"
      :columns="columns" :data="filteredItems" :loading="loading"
      :row-key="(r: Device) => r.id" :bordered="false"
    >
      <template #empty>
        <EmptyState description="还没有设备，订单「点亮上线」后设备会自动入库；也可用上方筛选按 SN / 状态 / 金租模式查找" />
      </template>
    </n-dataTable>

    <!-- 新增 / 编辑 -->
    <n-modal v-model:show="showEdit" preset="card" :title="editingId ? '编辑设备' : '新增设备'"
      style="width:560px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="SN（留空自动生成 GPU-{yyyymm}-{seq}）">
          <n-input v-model:value="form.sn" placeholder="留空自动生成" />
        </n-form-item>
        <n-space>
          <n-form-item label="项目" style="width:240px">
            <n-select v-model:value="form.project_id" :options="projectOpts()" placeholder="选项目" filterable
              :disabled="!!editingId" />
          </n-form-item>
          <n-form-item label="设备型号" style="width:240px">
            <n-select v-model:value="form.equipment_model_id" :options="equipOpts()" placeholder="选设备型号" filterable
              :disabled="!!editingId" />
          </n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="金租模式" style="width:150px">
            <n-select v-model:value="form.leasing_mode" :options="LEASING_OPTIONS" placeholder="金租模式" clearable />
          </n-form-item>
          <n-form-item label="权属" style="width:150px">
            <n-select v-model:value="form.ownership" :options="OWNERSHIP_OPTIONS" placeholder="权属" clearable />
          </n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="采购原值(元)"><n-input-number v-model:value="form.purchase_value" :min="0" :show-button="false" style="width:150px" /></n-form-item>
          <n-form-item label="月计费额(元/月)"><n-input-number v-model:value="form.monthly_price" :min="0" :show-button="false" style="width:150px" /></n-form-item>
          <n-form-item label="预付款(元)"><n-input-number v-model:value="form.prepayment_amount" :min="0" :show-button="false" style="width:150px" /></n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="关联订单" style="width:240px">
            <n-select v-model:value="form.order_id" :options="orderOpts()" placeholder="选订单（可选）" clearable filterable />
          </n-form-item>
          <n-form-item label="供应商" style="width:240px">
            <n-select v-model:value="form.supplier_id" :options="supplierOpts()" placeholder="选供应商（可选）" clearable filterable />
          </n-form-item>
        </n-space>
        <div v-if="editingId" style="font-size:12px;color:var(--c-text-3,#999)">
          状态由系统流转，批次通过「批次组合 / 移出批次」操作，均不在编辑表单内修改。
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEdit = false">取消</n-button>
          <n-button type="primary" @click="submitEdit">{{ editingId ? '保存' : '创建' }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 批次组合 -->
    <n-modal v-model:show="showBatchAssign" preset="card" title="批次组合" style="width:480px;max-width:94vw">
      <n-space vertical :size="12">
        <div style="font-size:13px">将选中的 {{ checkedRowKeys.length }} 台设备挂入批次订单：</div>
        <n-form-item label="批次订单">
          <n-select v-model:value="batchTarget" :options="orderOpts()" placeholder="选择批次订单" filterable />
        </n-form-item>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showBatchAssign = false">取消</n-button>
          <n-button type="primary" @click="submitBatchAssign">确认组合</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 销售批次组合 -->
    <n-modal v-model:show="showSalesBatchAssign" preset="card" title="销售批次组合" style="width:480px;max-width:94vw">
      <n-space vertical :size="12">
        <div style="font-size:13px">将选中的 {{ checkedRowKeys.length }} 台设备（SN）挂入销售批次：</div>
        <n-form-item label="销售批次">
          <n-select v-model:value="salesBatchTarget" :options="salesBatchOpts()" placeholder="选择销售批次" filterable />
        </n-form-item>
        <div style="font-size:12px;color:var(--c-text-3,#999)">
          销售批次与采购批次分开；销售验收按销售批次进行（一批一条验收）。
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showSalesBatchAssign = false">取消</n-button>
          <n-button type="primary" @click="submitSalesBatchAssign">确认组合</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- Excel 导入 -->
    <n-modal v-model:show="showImport" preset="card" title="Excel 批量导入" style="width:480px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="项目">
          <n-select v-model:value="importForm.project_id" :options="projectOpts()" placeholder="选项目" filterable />
        </n-form-item>
        <n-form-item label="设备型号">
          <n-select v-model:value="importForm.equipment_model_id" :options="equipOpts()" placeholder="选设备型号" filterable />
        </n-form-item>
        <n-form-item label="Excel 文件（.xlsx）">
          <input type="file" accept=".xlsx,.xls" @change="onFileChange" />
        </n-form-item>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showImport = false">取消</n-button>
          <n-button type="primary" @click="submitImport">上传导入</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 节点推进（单台 / 批量）-->
    <n-modal v-model:show="showAdvance" preset="card" title="节点推进" style="width:460px;max-width:94vw">
      <n-space vertical :size="12">
        <div style="font-size:13px">目标：{{ advanceTargetLabel }}</div>
        <n-form-item label="节点">
          <n-select v-model:value="advStage" :options="STATUS_OPTIONS" placeholder="选择节点" />
        </n-form-item>
        <n-form-item label="状态">
          <n-select v-model:value="advStatus" :options="STAGE_STATUS_OPTIONS" placeholder="选择状态" />
        </n-form-item>
        <n-form-item label="实际日期（可选）">
          <n-date-picker v-model:value="advDate" type="date" clearable style="width:100%" />
        </n-form-item>
        <div style="font-size:12px;color:var(--c-text-3,#999)">
          状态机：未开始→进行中；进行中→已完成/不合格；不合格→进行中（返工）。设备状态列随推进自动更新。
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAdvance = false">取消</n-button>
          <n-button type="primary" @click="submitAdvance">确认推进</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 回租出售（售后回租专属，W7-8）-->
    <n-modal v-model:show="showLeaseback" preset="card" title="回租出售" style="width:520px;max-width:94vw">
      <n-space vertical :size="12">
        <div style="font-size:13px">
          设备 {{ leasebackTarget?.sn }} · 售后回租表内自有。出售后：资产切已处置（折旧截断）+ 表外建档 + 确认长期应付款。
        </div>
        <n-form-item label="出售日" :show-feedback="false">
          <n-date-picker v-model:value="leasebackForm.sale_date" type="date" clearable style="width:100%" />
        </n-form-item>
        <n-form-item label="金租机构" :show-feedback="false">
          <n-select v-model:value="leasebackForm.leasing_org_id" :options="funderOpts" placeholder="选资金供应商" filterable />
        </n-form-item>
        <n-form-item label="出售价(元)" :show-feedback="false">
          <n-input-number v-model:value="leasebackForm.sale_price" :min="0" :show-button="false" style="width:200px" />
        </n-form-item>
        <n-form-item label="关联融资申请" :show-feedback="false">
          <n-select v-model:value="leasebackForm.leasing_process_id" :options="processOpts()" placeholder="选同项目 leasing_process" filterable />
        </n-form-item>
        <div style="font-size:12px;color:var(--c-text-3,#999)">
          出售不可自助撤销（折旧截断不自动红冲）；出售损益存入长期应付款，会计分录在二期。
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showLeaseback = false">取消</n-button>
          <n-button type="warning" @click="submitLeaseback">确认出售</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.inv-totals {
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
}
.inv-total { text-align: left; }
.inv-num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
}
.inv-num.green { color: #16A34A; }
.inv-num.blue { color: #2563EB; }
.inv-num.gray { color: #64748B; }
.inv-lbl { font-size: 12px; color: #64748B; margin-top: 2px; }
</style>
