<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  NAlert, NButton, NFormItem, NInput, NSelect, NSpin, useMessage,
} from 'naive-ui'
import { http } from '../../api/client'
import { errMsg } from '../../utils/errMsg'

// 客户确认（confirmation）：链式 create → confirm（客户确认人必填）
const props = defineProps<{ projectId: string; prefill: Record<string, any> }>()
const emit = defineEmits<{ (e: 'success'): void }>()
const msg = useMessage()
const loading = ref(true)
const submitting = ref(false)

const salesOrders = ref<any[]>([])
const billings = ref<any[]>([])

const form = ref({
  billing_id: null as string | null,
  sales_order_id: null as string | null,
  period_label: '',
  confirmed_by_customer: '',
})

const billingOptions = computed(() => billings.value.map((b: any) => ({
  label: `${b.period_label} · 金额 ${b.amount} · ${b.status}`,
  value: b.id,
})))
const salesOrderOptions = computed(() => salesOrders.value.map((s: any) => ({
  label: `销售订单 ${String(s.id).slice(0, 8)} · 月租 ${s.total_monthly_rent}`,
  value: s.id,
})))

watch(() => form.value.billing_id, (id) => {
  const b = billings.value.find((x: any) => x.id === id)
  if (b) form.value.period_label = b.period_label
})

onMounted(async () => {
  try {
    const [{ data: so }, { data: od }, { data: bl }] = await Promise.all([
      http.get('/sales-orders', { params: { project_id: props.projectId } }),
      http.get('/orders', { params: { project_id: props.projectId } }),
      http.get('/billings'),
    ])
    salesOrders.value = so || []
    // 计费列表无 project_id 过滤，按该项目订单的 order_id 在本地过滤
    const orderIds = new Set((od.items || []).map((o: any) => o.id))
    billings.value = (bl.items || []).filter((b: any) => orderIds.has(b.order_id))
    if (salesOrders.value.length === 1) form.value.sales_order_id = salesOrders.value[0].id
    if (billings.value.length === 1) form.value.billing_id = billings.value[0].id
  } catch (e: any) { msg.error(errMsg(e)) } finally { loading.value = false }
})

async function submit() {
  if (!form.value.billing_id) { msg.warning('请选择计费单'); return }
  if (!form.value.sales_order_id) { msg.warning('请选择销售订单'); return }
  if (!form.value.period_label) { msg.warning('请填写期间标签'); return }
  if (!form.value.confirmed_by_customer) { msg.warning('请填写客户确认人'); return }
  submitting.value = true
  try {
    // 第 1 步：创建确认单
    const { data: sc } = await http.post('/confirmations', {
      billing_id: form.value.billing_id,
      sales_order_id: form.value.sales_order_id,
      period_label: form.value.period_label,
    })
    // 第 2 步：客户确认
    try {
      await http.post(`/confirmations/${sc.id}/confirm`, null, {
        params: { confirmed_by_customer: form.value.confirmed_by_customer },
      })
    } catch (e: any) {
      msg.error(`确认单已创建，但客户确认失败：${errMsg(e)}`)
      return
    }
    msg.success('客户确认已提交')
    emit('success')
  } catch (e: any) { msg.error(errMsg(e)) } finally { submitting.value = false }
}
</script>

<template>
  <n-spin :show="loading">
    <n-alert v-if="!loading && !billings.length" type="warning" :bordered="false" style="margin-bottom:12px">
      该项目暂无计费单，请先完成「计费」步骤
    </n-alert>
    <n-form-item label="计费单" required>
      <n-select v-model:value="form.billing_id" :options="billingOptions" placeholder="选择计费单" />
    </n-form-item>
    <n-form-item label="销售订单" required>
      <n-select v-model:value="form.sales_order_id" :options="salesOrderOptions" placeholder="选择销售订单" />
    </n-form-item>
    <n-form-item label="期间标签" required>
      <n-input v-model:value="form.period_label" placeholder="如：2026-08 第1期" />
    </n-form-item>
    <n-form-item label="客户确认人" required>
      <n-input v-model:value="form.confirmed_by_customer" placeholder="客户方确认人姓名" />
    </n-form-item>
    <n-button type="primary" block :loading="submitting" @click="submit">提交客户确认</n-button>
  </n-spin>
</template>
