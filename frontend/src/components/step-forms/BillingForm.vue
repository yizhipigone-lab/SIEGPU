<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NAlert, NButton, NDatePicker, NFormItem, NInputNumber, NSelect, NSpin, useMessage,
} from 'naive-ui'
import { http } from '../../api/client'
import { errMsg } from '../../utils/errMsg'

// 生成计费（billing_confirm）：选订单 + 销售合同 + 期数 + 计费日
const props = defineProps<{ projectId: string; prefill: Record<string, any> }>()
const emit = defineEmits<{ (e: 'success'): void }>()
const msg = useMessage()
const loading = ref(true)
const submitting = ref(false)

const orders = ref<any[]>([])
const contracts = ref<any[]>([])

// NDatePicker 绑定时间戳，提交时转 YYYY-MM-DD
function toDateStr(ts: number | null): string | null {
  if (!ts) return null
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

const form = ref({
  order_id: null as string | null,
  contract_id: null as string | null,
  period_index: 1,
  billing_date: Date.now() as number | null,
})

const orderOptions = computed(() => orders.value.map((o: any) => ({
  label: `订单 ${String(o.id).slice(0, 8)} · 数量 ${o.quantity} · ${o.status}`,
  value: o.id,
})))
const contractOptions = computed(() => contracts.value.map((c: any) => ({
  label: `${c.contract_no || String(c.id).slice(0, 8)} · 金额 ${c.amount}`,
  value: c.id,
})))

onMounted(async () => {
  try {
    const [{ data: od }, { data: cd }] = await Promise.all([
      http.get('/orders', { params: { project_id: props.projectId } }),
      http.get('/contracts', { params: { project_id: props.projectId, type: 'SALES' } }),
    ])
    orders.value = od.items || []
    contracts.value = cd.items || []
    if (orders.value.length === 1) form.value.order_id = orders.value[0].id
    if (contracts.value.length === 1) form.value.contract_id = contracts.value[0].id
  } catch (e: any) { msg.error(errMsg(e)) } finally { loading.value = false }
})

async function submit() {
  if (!form.value.order_id) { msg.warning('请选择订单'); return }
  if (!form.value.contract_id) { msg.warning('请选择销售合同'); return }
  if (!form.value.billing_date) { msg.warning('请选择计费日期'); return }
  submitting.value = true
  try {
    await http.post('/billings', {
      order_id: form.value.order_id,
      contract_id: form.value.contract_id,
      period_index: form.value.period_index,
      billing_date: toDateStr(form.value.billing_date),
    })
    msg.success('计费已生成')
    emit('success')
  } catch (e: any) { msg.error(errMsg(e)) } finally { submitting.value = false }
}
</script>

<template>
  <n-spin :show="loading">
    <n-alert v-if="!loading && !orders.length" type="warning" :bordered="false" style="margin-bottom:12px">
      该项目暂无采购订单，请先完成前面的订单步骤
    </n-alert>
    <n-alert v-if="!loading && !contracts.length" type="warning" :bordered="false" style="margin-bottom:12px">
      该项目暂无销售合同，请先完成前面的合同步骤
    </n-alert>
    <n-form-item label="订单" required>
      <n-select v-model:value="form.order_id" :options="orderOptions" placeholder="选择订单" />
    </n-form-item>
    <n-form-item label="销售合同" required>
      <n-select v-model:value="form.contract_id" :options="contractOptions" placeholder="选择销售合同" />
    </n-form-item>
    <n-form-item label="期数" required>
      <n-input-number v-model:value="form.period_index" :min="1" style="width:100%" />
    </n-form-item>
    <n-form-item label="计费日期" required>
      <n-date-picker v-model:value="form.billing_date" type="date" style="width:100%" />
    </n-form-item>
    <n-button type="primary" block :loading="submitting" @click="submit">生成计费</n-button>
  </n-spin>
</template>
