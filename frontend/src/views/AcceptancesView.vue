<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NDataTable, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpace, NTag, useMessage,
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
}

const msg = useMessage()
const route = useRoute()
const items = ref<Acceptance[]>([])
const loading = ref(false)

// 下拉数据源
const projects = ref<any[]>([])
const orders = ref<any[]>([])
const salesOrders = ref<any[]>([])

// 新建表单
const showCreate = ref(false)
const form = ref({
  project_id: '' as string, acceptance_type: '采购验收' as string,
  order_id: null as string | null, sales_order_id: null as string | null,
  inspector: '', quantity_accepted: 0, quantity_rejected: 0, notes: '',
})

// 驳回弹窗
const rejectTarget = ref<Acceptance | null>(null)
const rejectReason = ref('')
const showReject = computed({
  get: () => !!rejectTarget.value,
  set: (v: boolean) => { if (!v) { rejectTarget.value = null; rejectReason.value = '' } },
})

const projectOpts = () => projects.value.map((p: any) => ({ label: p.name, value: p.id }))
const orderOpts = () => orders.value.map((o: any) => ({
  label: `采购单 ${o.id.slice(0, 8)}… · ${o.quantity}台`, value: o.id,
}))
const salesOrderOpts = () => salesOrders.value.map((s: any) => ({
  label: `销售单 ${s.id.slice(0, 8)}… · ${s.quantity}台`, value: s.id,
}))
const projectName = (id: string) => projects.value.find((p: any) => p.id === id)?.name || id.slice(0, 8) + '…'

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
    project_id: (route.query.project_id as string) || '', acceptance_type: '采购验收',
    order_id: null, sales_order_id: null,
    inspector: '', quantity_accepted: 0, quantity_rejected: 0, notes: '',
  }
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
      inspector: f.inspector || null,
      quantity_accepted: f.quantity_accepted, quantity_rejected: f.quantity_rejected,
      notes: f.notes || null,
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
    <n-dataTable :columns="columns" :data="items" :loading="loading" :bordered="false">
      <template #empty>
        <EmptyState description="还没有验收记录，点击右上角「新建验收」，设备到货后即可登记验收" />
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
        <n-form-item v-if="form.acceptance_type === '采购验收'" label="关联采购订单">
          <n-select v-model:value="form.order_id" :options="orderOpts()" placeholder="选采购订单" filterable />
        </n-form-item>
        <n-form-item v-else label="关联销售订单">
          <n-select v-model:value="form.sales_order_id" :options="salesOrderOpts()" placeholder="选销售订单" filterable />
        </n-form-item>
        <n-space>
          <n-form-item label="验收人"><n-input v-model:value="form.inspector" style="width:130px" /></n-form-item>
          <n-form-item label="合格数(台)"><n-input-number v-model:value="form.quantity_accepted" :min="0" style="width:100px" /></n-form-item>
          <n-form-item label="不合格数(台)"><n-input-number v-model:value="form.quantity_rejected" :min="0" style="width:100px" /></n-form-item>
        </n-space>
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
