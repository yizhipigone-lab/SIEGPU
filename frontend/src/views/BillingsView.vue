<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NDataTable, NFormItem, NInput, NInputNumber, NModal, NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money } from '../utils/format'

const msg = useMessage()
const route = useRoute()
const items = ref<any[]>([])
const loading = ref(false)

// 下拉数据源
const projects = ref<any[]>([])
const orders = ref<any[]>([])
const contracts = ref<any[]>([])

// 生成计费表单
const showCreate = ref(false)
const form = ref({
  project_id: null as string | null,
  order_id: '' as string, contract_id: '' as string,
  period_index: null as number | null, billing_date: '',
})

const projectOpts = () => projects.value.map((p: any) => ({ label: p.name, value: p.id }))
const orderOpts = () => orders.value
  .filter((o: any) => !form.value.project_id || o.project_id === form.value.project_id)
  .map((o: any) => ({ label: `订单 ${o.id.slice(0, 8)}… · ${o.quantity}台 · ${money(o.total_amount)}`, value: o.id }))
const contractOpts = () => contracts.value
  .filter((c: any) => c.type === 'SALES')
  .map((c: any) => ({ label: `${c.contract_no || c.id.slice(0, 8)} (销售)`, value: c.id }))

const contractNo = (id: string) => contracts.value.find((c: any) => c.id === id)?.contract_no || id.slice(0, 8) + '…'

const columns = [
  { title: '计费期', key: 'period_label', width: 110 },
  { title: '订单', key: 'order_id', width: 110, render: (r: any) => `${r.order_id.slice(0, 8)}…` },
  { title: '合同', key: 'contract_id', width: 130, render: (r: any) => contractNo(r.contract_id) },
  { title: '计费日', key: 'billing_date', width: 110 },
  { title: '天数', key: 'days_in_period', width: 60 },
  { title: '含税金额', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
  { title: '不含税', key: 'amount_ex_tax', align: 'right' as const, render: (r: any) => money(r.amount_ex_tax) },
  { title: '税额', key: 'tax_amount', align: 'right' as const, render: (r: any) => money(r.tax_amount) },
  { title: '状态', key: 'status', width: 90, render: (r: any) =>
      h(NTag, { size: 'small', type: r.status === '已确认' ? 'success' : 'default' }, () => r.status) },
]

async function load() {
  loading.value = true
  try {
    const [b, p, o, c] = await Promise.all([
      api.get('/billings'), api.get('/projects'), api.get('/orders'), api.get('/contracts'),
    ])
    items.value = b.data.items
    projects.value = p.data.items
    orders.value = o.data.items
    contracts.value = c.data.items
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}

function openCreate() {
  form.value = {
    project_id: (route.query.project_id as string) || null, order_id: '', contract_id: '',
    period_index: null, billing_date: new Date().toISOString().slice(0, 10),
  }
  showCreate.value = true
}

async function submitCreate() {
  const f = form.value
  if (!f.order_id || !f.contract_id) { msg.warning('请选择订单和合同'); return }
  if (!f.period_index || !f.billing_date) { msg.warning('请填期数和计费日期'); return }
  try {
    await api.post('/billings', {
      order_id: f.order_id, contract_id: f.contract_id,
      period_index: f.period_index, billing_date: f.billing_date,
      idempotency_key: `${f.order_id}-${f.period_index}`,
    })
    msg.success('计费单已生成')
    showCreate.value = false
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">计费管理</h2>
      <n-button type="primary" @click="openCreate">生成计费</n-button>
    </div>
    <n-data-table :columns="columns" :data="items" :loading="loading" :bordered="false" size="small" striped />

    <n-modal v-model:show="showCreate" preset="card" title="生成计费" style="width:480px;max-width:94vw">
      <n-space vertical :size="12">
        <n-form-item label="项目（用于筛选订单）">
          <n-select v-model:value="form.project_id" :options="projectOpts()" placeholder="全部项目" filterable clearable />
        </n-form-item>
        <n-form-item label="订单">
          <n-select v-model:value="form.order_id" :options="orderOpts()" placeholder="选订单" filterable />
        </n-form-item>
        <n-form-item label="销售合同">
          <n-select v-model:value="form.contract_id" :options="contractOpts()" placeholder="选销售合同" filterable />
        </n-form-item>
        <n-space>
          <n-form-item label="计费期数"><n-input-number v-model:value="form.period_index" :min="1" style="width:110px" /></n-form-item>
          <n-form-item label="计费日期"><n-input v-model:value="form.billing_date" placeholder="YYYY-MM-DD" style="width:150px" /></n-form-item>
        </n-space>
        <div class="muted tiny">同一订单同一期数只能生成一次（重复提交会提示"已存在"）。</div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" @click="submitCreate">生成</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
