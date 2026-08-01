<script setup lang="ts">
import { h, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NDataTable, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'

interface SalesOrder {
  id: string; project_id: string; contract_id: string
  equipment_model_id: string; quantity: number
  monthly_rent_per_unit: number; total_monthly_rent: number
  start_date: string | null; end_date: string | null
  status: string; notes: string | null
  created_at: string
}

const msg = useMessage()
const route = useRoute()
const items = ref<SalesOrder[]>([])
const loading = ref(false)

// 下拉数据源
const projects = ref<any[]>([])
const contracts = ref<any[]>([])
const equipModels = ref<any[]>([])

// 新增表单
const showCreate = ref(false)
const form = ref({
  project_id: '' as string, contract_id: '' as string, equipment_model_id: '' as string,
  quantity: null as number | null, monthly_rent_per_unit: null as number | null,
  total_monthly_rent: null as number | null,
  start_date: '', end_date: '', notes: '',
})

// 数量或单价变化时自动算总月租（可手改）
watch([() => form.value.quantity, () => form.value.monthly_rent_per_unit], ([q, u]) => {
  if (q && u) form.value.total_monthly_rent = Math.round(q * u * 100) / 100
})

const projectOpts = () => projects.value.map((p: any) => ({ label: p.name, value: p.id }))
const contractOpts = () => contracts.value
  .filter((c: any) => c.type === 'SALES')
  .map((c: any) => ({ label: `${c.contract_no || c.id.slice(0, 8)} (销售)`, value: c.id }))
const equipOpts = () => equipModels.value.map((m: any) => ({
  label: `${m.name}${m.gpu_type ? ` · ${m.gpu_type}x${m.gpu_count}` : ''}`, value: m.id,
}))

const projectName = (id: string) => projects.value.find((p: any) => p.id === id)?.name || id.slice(0, 8) + '…'
const contractNo = (id: string) => contracts.value.find((c: any) => c.id === id)?.contract_no || id.slice(0, 8) + '…'
const equipName = (id: string) => equipModels.value.find((m: any) => m.id === id)?.name || id.slice(0, 8) + '…'

const columns = [
  { title: '项目', key: 'project_id', render: (r: any) => projectName(r.project_id) },
  { title: '合同', key: 'contract_id', width: 130, render: (r: any) => contractNo(r.contract_id) },
  { title: '设备型号', key: 'equipment_model_id', render: (r: any) => equipName(r.equipment_model_id) },
  { title: '数量', key: 'quantity', width: 70 },
  { title: '月租/台', key: 'monthly_rent_per_unit', align: 'right' as const, render: (r: any) => r.monthly_rent_per_unit?.toLocaleString() },
  { title: '总月租', key: 'total_monthly_rent', align: 'right' as const, render: (r: any) => r.total_monthly_rent?.toLocaleString() },
  { title: '起租', key: 'start_date', width: 110 },
  { title: '止租', key: 'end_date', width: 110 },
  { title: '状态', key: 'status', width: 90, render: (r: any) => h(NTag, { type: r.status === '执行中' ? 'success' : 'default', size: 'small' }, () => r.status) },
]

async function load() {
  loading.value = true
  try {
    const [so, proj, con, eq] = await Promise.all([
      http.get('/sales-orders'), http.get('/projects'), http.get('/contracts'), http.get('/equipment-models'),
    ])
    items.value = so.data
    projects.value = proj.data.items
    contracts.value = con.data.items
    equipModels.value = eq.data.items
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}

function openCreate() {
  form.value = {
    project_id: (route.query.project_id as string) || '', contract_id: '', equipment_model_id: '',
    quantity: null, monthly_rent_per_unit: null, total_monthly_rent: null,
    start_date: '', end_date: '', notes: '',
  }
  showCreate.value = true
}

async function submitCreate() {
  const f = form.value
  if (!f.project_id || !f.contract_id || !f.equipment_model_id) { msg.warning('请选择项目/合同/设备型号'); return }
  if (!f.quantity || !f.monthly_rent_per_unit) { msg.warning('请填数量和月租单价'); return }
  try {
    await http.post('/sales-orders', {
      project_id: f.project_id, contract_id: f.contract_id, equipment_model_id: f.equipment_model_id,
      quantity: f.quantity, monthly_rent_per_unit: f.monthly_rent_per_unit,
      total_monthly_rent: f.total_monthly_rent ?? f.quantity * f.monthly_rent_per_unit,
      start_date: f.start_date || null, end_date: f.end_date || null, notes: f.notes || null,
    })
    msg.success('销售订单已创建')
    showCreate.value = false
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">销售订单</h2>
      <n-button type="primary" @click="openCreate">新增销售订单</n-button>
    </div>
    <n-dataTable :columns="columns" :data="items" :loading="loading" :bordered="false" />

    <n-modal v-model:show="showCreate" preset="card" title="新增销售订单" style="width:520px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="项目">
          <n-select v-model:value="form.project_id" :options="projectOpts()" placeholder="选项目" filterable />
        </n-form-item>
        <n-form-item label="销售合同">
          <n-select v-model:value="form.contract_id" :options="contractOpts()" placeholder="选销售合同" filterable />
        </n-form-item>
        <n-form-item label="设备型号">
          <n-select v-model:value="form.equipment_model_id" :options="equipOpts()" placeholder="选设备型号" filterable />
        </n-form-item>
        <n-space>
          <n-form-item label="数量"><n-input-number v-model:value="form.quantity" :min="1" style="width:120px" /></n-form-item>
          <n-form-item label="月租/台(含税)"><n-input-number v-model:value="form.monthly_rent_per_unit" :show-button="false" style="width:150px" /></n-form-item>
          <n-form-item label="总月租"><n-input-number v-model:value="form.total_monthly_rent" :show-button="false" style="width:150px" /></n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="起租日"><n-input v-model:value="form.start_date" placeholder="YYYY-MM-DD" style="width:140px" /></n-form-item>
          <n-form-item label="止租日"><n-input v-model:value="form.end_date" placeholder="YYYY-MM-DD" style="width:140px" /></n-form-item>
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
  </div>
</template>
