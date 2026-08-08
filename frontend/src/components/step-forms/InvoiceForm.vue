<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert, NButton, NDatePicker, NFormItem, NInput, NInputNumber, NSelect, NSpin, useMessage,
} from 'naive-ui'
import { http } from '../../api/client'
import { errMsg } from '../../utils/errMsg'
import { tsToYmd } from '../../utils/format'

// 开票（invoice_issue）：create → pay（填了收款日期才执行）→ reconcile（选了流水才执行）
// 未核销时在抽屉内提示到发票对账页完成核销并给出跳转
const props = defineProps<{ projectId: string; prefill: Record<string, any> }>()
const emit = defineEmits<{ (e: 'success'): void }>()
const router = useRouter()
const msg = useMessage()
const loading = ref(true)
const submitting = ref(false)

const contracts = ref<any[]>([])
const txns = ref<any[]>([])

const form = ref({
  contract_id: null as string | null,
  invoice_no: '',
  amount: null as number | null,
  issue_date: Date.now() as number | null,
  due_date: null as number | null,
  paid_date: null as number | null,
  txn_id: null as string | null,
})

const contractOptions = computed(() => contracts.value.map((c: any) => ({
  label: `${c.contract_no || String(c.id).slice(0, 8)} · 金额 ${c.amount}`,
  value: c.id,
})))
const txnOptions = computed(() => txns.value.map((t: any) => ({
  label: `${t.transaction_date} · ${t.source_type} · ${t.amount}`,
  value: t.id,
})))

onMounted(async () => {
  try {
    const [{ data: cd }, { data: td }] = await Promise.all([
      http.get('/contracts', { params: { project_id: props.projectId, type: 'SALES' } }),
      http.get('/capital/transactions', { params: { project_id: props.projectId, direction: 'IN' } }),
    ])
    contracts.value = cd.items || []
    txns.value = td.items || []
    if (contracts.value.length === 1) form.value.contract_id = contracts.value[0].id
  } catch (e: any) { msg.error(errMsg(e)) } finally { loading.value = false }
})

function goReconcile() {
  router.push({ path: '/invoices', query: { project_id: props.projectId } })
  emit('success')
}

async function submit() {
  if (!form.value.contract_id) { msg.warning('请选择销售合同'); return }
  if (form.value.amount === null || form.value.amount < 0) { msg.warning('请填写开票金额'); return }
  if (!form.value.issue_date) { msg.warning('请选择开票日期'); return }
  submitting.value = true
  try {
    // 第 1 步：开票
    const { data: inv } = await http.post('/invoices', {
      contract_id: form.value.contract_id,
      invoice_no: form.value.invoice_no || null,
      amount: form.value.amount,
      issue_date: tsToYmd(form.value.issue_date) || null,
      due_date: tsToYmd(form.value.due_date) || null,
    })
    // 第 2 步：登记收款（选填）
    if (form.value.paid_date) {
      try {
        await http.post(`/invoices/${inv.id}/pay`, { paid_date: tsToYmd(form.value.paid_date) || null })
      } catch (e: any) {
        msg.error(`发票已开具，但登记收款失败：${errMsg(e)}`)
        return
      }
    }
    // 第 3 步：核销（选了流水才执行）
    if (form.value.txn_id) {
      try {
        await http.post(`/invoices/${inv.id}/reconcile/${form.value.txn_id}`)
        msg.success('开票 + 收款 + 核销已完成')
        emit('success')
        return
      } catch (e: any) {
        msg.error(`发票已开具，但核销失败：${errMsg(e)}`)
        return
      }
    }
    // 未核销：提示到发票对账页完成
    msg.success('发票已开具')
    reconciledPending.value = true
  } catch (e: any) { msg.error(errMsg(e)) } finally { submitting.value = false }
}

const reconciledPending = ref(false)
</script>

<template>
  <n-spin :show="loading">
    <n-alert v-if="!loading && !contracts.length" type="warning" :bordered="false" style="margin-bottom:12px">
      该项目暂无销售合同，请先完成前面的合同步骤
    </n-alert>
    <n-form-item label="销售合同" required>
      <n-select v-model:value="form.contract_id" :options="contractOptions" placeholder="选择销售合同" />
    </n-form-item>
    <n-form-item label="发票号">
      <n-input v-model:value="form.invoice_no" placeholder="选填" />
    </n-form-item>
    <n-form-item label="开票金额(含税,元)" required>
      <n-input-number v-model:value="form.amount" :min="0" :show-button="false" style="width:100%" />
    </n-form-item>
    <n-form-item label="开票日期" required>
      <n-date-picker v-model:value="form.issue_date" type="date" style="width:100%" />
    </n-form-item>
    <n-form-item label="到期日">
      <n-date-picker v-model:value="form.due_date" type="date" style="width:100%" clearable />
    </n-form-item>
    <n-form-item label="收款日期（已收款则填）">
      <n-date-picker v-model:value="form.paid_date" type="date" style="width:100%" clearable />
    </n-form-item>
    <n-form-item label="核销流水（选填）">
      <n-select
        v-model:value="form.txn_id" :options="txnOptions" clearable
        placeholder="选择该项目入金流水进行核销"
      />
    </n-form-item>

    <n-alert v-if="reconciledPending" type="info" :bordered="false" style="margin-bottom:12px">
      发票已开具但尚未核销。可前往发票对账页完成核销：
      <n-button size="tiny" type="primary" style="margin-left:8px" @click="goReconcile">去发票对账</n-button>
    </n-alert>

    <n-button v-if="!reconciledPending" type="primary" block :loading="submitting" @click="submit">开票</n-button>
  </n-spin>
</template>
