<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCheckbox, NDataTable, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpace,
  NTabPane, NTabs, NTag, useMessage,
} from 'naive-ui'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { statusTagType } from '../utils/format'
import EmptyState from '../components/EmptyState.vue'
interface Acceptance {
  id: string; project_id: string; acceptance_type: string
  order_id: string | null; sales_order_id: string | null
  status: string; inspector: string | null; acceptance_date: string | null
  quantity_accepted: number; quantity_rejected: number
  shelve: boolean
}

const msg = useMessage()
const route = useRoute()
const items = ref<Acceptance[]>([])
const loading = ref(false)

// 下拉数据源
const projects = ref<any[]>([])
const orders = ref<any[]>([])
const salesOrders = ref<any[]>([])

// W4：采购验收 / 销售验收 Tab 切换
const activeType = ref<'采购验收' | '销售验收'>('采购验收')
const filteredItems = computed(() => items.value.filter((a) => a.acceptance_type === activeType.value))

// 新建表单
const showCreate = ref(false)
const todayStr = () => new Date().toISOString().slice(0, 10)
const form = ref({
  project_id: '' as string, acceptance_type: '采购验收' as string,
  order_id: null as string | null, sales_order_id: null as string | null,
  acceptance_date: todayStr(),  // 缺陷#5：验收日期可录入（默认今天）
  inspector: '', quantity_accepted: 0, quantity_rejected: 0, notes: '',
  shelve: false,
})
// 缺陷#5：验收与设备清单勾稽——采购验收选中批次后展示批内设备（SN/状态，只读）
const batchDevices = ref<any[]>([])
watch(() => [form.value.order_id, form.value.acceptance_type], async ([oid, type]) => {
  batchDevices.value = []
  if (type !== '采购验收' || !oid) return
  try {
    const { data } = await http.get('/devices', { params: { batch_id: oid } })
    batchDevices.value = data.items || []
  } catch { batchDevices.value = [] }
})

// 驳回弹窗
const rejectTarget = ref<Acceptance | null>(null)
const rejectReason = ref('')
const showReject = computed({
  get: () => !!rejectTarget.value,
  set: (v: boolean) => { if (!v) { rejectTarget.value = null; rejectReason.value = '' } },
})

const projectOpts = () => projects.value.map((p: any) => ({ label: p.name, value: p.id }))
// W4：按批次验收——下拉清晰标注「批次」与批次名
const orderOpts = () => orders.value.map((o: any) => ({
  label: o.is_batch
    ? `批次 ${o.batch_name || o.id.slice(0, 8)} · ${o.quantity ?? '?'}台`
    : `采购单 ${o.id.slice(0, 8)} · ${o.quantity}台`,
  value: o.id,
}))
const salesOrderOpts = () => salesOrders.value.map((s: any) => ({
  label: s.is_batch
    ? `销售批次 ${s.batch_name || s.id.slice(0, 8)} · ${s.quantity}台`
    : `销售单 ${s.id.slice(0, 8)} · ${s.quantity}台`,
  value: s.id,
}))
const projectName = (id: string) => projects.value.find((p: any) => p.id === id)?.name || id.slice(0, 8) + '…'
const batchLabel = (r: Acceptance) => {
  const id = r.acceptance_type === '采购验收' ? r.order_id : r.sales_order_id
  if (!id) return '—'
  const list = r.acceptance_type === '采购验收' ? orders.value : salesOrders.value
  const o = list.find((x: any) => x.id === id)
  return o ? (o.batch_name || o.id.slice(0, 8)) : id.slice(0, 8) + '…'
}

async function approve(row: Acceptance) {
  try {
    await http.post(`/acceptances/${row.id}/approve`)
    msg.success('已通过验收')
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

function openReject(row: Acceptance) { rejectTarget.value = row; rejectReason.value = '' }

async function submitReject() {
  if (!rejectTarget.value) return
  if (!rejectReason.value.trim()) { msg.warning('请填驳回原因'); return }
  try {
    await http.post(`/acceptances/${rejectTarget.value.id}/reject`, null, { params: { reason: rejectReason.value } })
    msg.success('已驳回')
    rejectTarget.value = null; rejectReason.value = ''
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

const columns = [
  { title: '项目', key: 'project_id', render: (r: any) => projectName(r.project_id) },
  { title: '类型', key: 'acceptance_type', width: 100, render: (r: any) => h(NTag, { type: r.acceptance_type === '采购验收' ? 'info' : 'success', size: 'small' }, () => r.acceptance_type) },
  { title: '批次', key: 'order_id', width: 150, render: (r: Acceptance) => batchLabel(r) },
  { title: '状态', key: 'status', width: 90, render: (r: any) => h(NTag, { type: statusTagType(r.status) as any, size: 'small' }, () => r.status) },
  { title: '验收人', key: 'inspector', width: 100 },
  { title: '合格', key: 'quantity_accepted', width: 70 },
  { title: '不合格', key: 'quantity_rejected', width: 80 },
  { title: '日期', key: 'acceptance_date', width: 110 },
  { title: '操作', key: '__op', width: 130, render: (r: Acceptance) =>
      (r.status === '待验收' || r.status === '验收中')
        ? h(NSpace, { size: 4 }, () => [
            h(NButton, { size: 'tiny', type: 'primary', quaternary: true, onClick: () => approve(r) }, () => '通过'),
            h(NButton, { size: 'tiny', type: 'error', quaternary: true, onClick: () => openReject(r) }, () => '驳回'),
          ])
        : null },
]

async function load() {
  loading.value = true
  try {
    const [ar, proj, ord, so] = await Promise.all([
      http.get('/acceptances'), http.get('/projects'), http.get('/orders'), http.get('/sales-orders'),
    ])
    items.value = ar.data
    projects.value = proj.data.items
    orders.value = ord.data.items
    salesOrders.value = so.data
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}

function openCreate() {
  form.value = {
    project_id: (route.query.project_id as string) || '', acceptance_type: activeType.value,
    order_id: null, sales_order_id: null,
    acceptance_date: todayStr(),
    inspector: '', quantity_accepted: 0, quantity_rejected: 0, notes: '', shelve: false,
  }
  batchDevices.value = []
  showCreate.value = true
}

async function submitCreate() {
  const f = form.value
  if (!f.project_id) { msg.warning('请选择项目'); return }
  if (f.acceptance_type === '采购验收' && !f.order_id) { msg.warning('采购验收必须关联采购订单'); return }
  if (f.acceptance_type === '销售验收' && !f.sales_order_id) { msg.warning('销售验收必须关联销售订单'); return }
  try {
    await http.post('/acceptances', {
      project_id: f.project_id, acceptance_type: f.acceptance_type,
      order_id: f.acceptance_type === '采购验收' ? f.order_id : null,
      sales_order_id: f.acceptance_type === '销售验收' ? f.sales_order_id : null,
      acceptance_date: f.acceptance_date || todayStr(),
      inspector: f.inspector || null,
      quantity_accepted: f.quantity_accepted, quantity_rejected: f.quantity_rejected,
      notes: f.notes || null,
      shelve: f.acceptance_type === '销售验收' ? f.shelve : false,
    })
    msg.success('验收单已创建')
    showCreate.value = false
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">验收管理</h2>
      <n-button type="primary" @click="openCreate">新建验收</n-button>
    </div>

    <n-tabs v-model:value="activeType" type="line" style="margin-bottom:12px" data-testid="acceptance-tabs">
      <n-tab-pane name="采购验收" tab="采购验收" />
      <n-tab-pane name="销售验收" tab="销售验收" />
    </n-tabs>

    <n-dataTable :columns="columns" :data="filteredItems" :loading="loading" :bordered="false">
      <template #empty>
        <EmptyState description="还没有验收记录，点击右上角「新建验收」，设备到货/交付后即可按批次登记验收" />
      </template>
    </n-dataTable>

    <!-- 新建验收 -->
    <n-modal v-model:show="showCreate" preset="card" title="新建验收" style="width:480px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="项目">
          <n-select v-model:value="form.project_id" :options="projectOpts()" placeholder="选项目" filterable />
        </n-form-item>
        <n-form-item label="验收类型">
          <n-select v-model:value="form.acceptance_type" :options="[{ label: '采购验收', value: '采购验收' }, { label: '销售验收', value: '销售验收' }]" />
        </n-form-item>
        <n-form-item v-if="form.acceptance_type === '采购验收'" label="关联采购批次">
          <n-select v-model:value="form.order_id" :options="orderOpts()" placeholder="选采购批次订单" filterable />
        </n-form-item>
        <n-form-item v-else label="关联销售批次">
          <n-select v-model:value="form.sales_order_id" :options="salesOrderOpts()" placeholder="选销售批次" filterable />
        </n-form-item>
        <!-- 缺陷#5：验收与设备清单勾稽（采购验收批次设备，只读） -->
        <div v-if="batchDevices.length" style="font-size:12px;color:var(--c-text-2,#666);background:#F8FAFC;border-radius:6px;padding:8px 10px">
          <div style="margin-bottom:4px">本批次 {{ batchDevices.length }} 台设备：</div>
          <n-space :size="2" wrap>
            <n-tag v-for="d in batchDevices" :key="d.id" size="tiny" :bordered="false"
              :type="d.status === '点亮验收' ? 'success' : 'default'">{{ d.sn }} · {{ d.status }}</n-tag>
          </n-space>
        </div>
        <n-space>
          <n-form-item label="验收日期">
            <n-date-picker :value="form.acceptance_date ? new Date(form.acceptance_date).getTime() : null" type="date" style="width:150px"
              @update:value="(ts: any) => { if (ts) form.acceptance_date = new Date(ts).toISOString().slice(0, 10) }" />
          </n-form-item>
          <n-form-item label="验收人"><n-input v-model:value="form.inspector" style="width:130px" /></n-form-item>
          <n-form-item label="合格数(台)"><n-input-number v-model:value="form.quantity_accepted" :min="0" style="width:100px" /></n-form-item>
          <n-form-item label="不合格数(台)"><n-input-number v-model:value="form.quantity_rejected" :min="0" style="width:100px" /></n-form-item>
        </n-space>
        <n-form-item v-if="form.acceptance_type === '销售验收'" label="上架">
          <n-checkbox v-model:checked="form.shelve">
            勾选后，验收通过时同步把该批次订单的上架标记为完成
          </n-checkbox>
        </n-form-item>
        <n-form-item label="备注"><n-input v-model:value="form.notes" type="textarea" :rows="2" /></n-form-item>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" @click="submitCreate">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 驳回原因 -->
    <n-modal v-model:show="showReject" preset="card" title="驳回验收" style="width:380px">
      <n-form-item label="驳回原因">
        <n-input v-model:value="rejectReason" type="textarea" :rows="2" placeholder="必填" />
      </n-form-item>
      <template #footer>
        <n-space justify="end">
          <n-button @click="rejectTarget = null">取消</n-button>
          <n-button type="error" @click="submitReject">确认驳回</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
