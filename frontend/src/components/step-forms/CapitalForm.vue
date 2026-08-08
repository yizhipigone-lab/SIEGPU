<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NButton, NDatePicker, NFormItem, NInput, NInputNumber, NSelect, useMessage,
} from 'naive-ui'
import { http } from '../../api/client'
import { errMsg } from '../../utils/errMsg'
import { tsToYmd } from '../../utils/format'

// 资金入金（capital_in）/ 出金（capital_out）共用表单，方向来自 step.prefill.direction
const props = defineProps<{ projectId: string; prefill: Record<string, any> }>()
const emit = defineEmits<{ (e: 'success'): void }>()
const msg = useMessage()
const submitting = ref(false)

const isIn = computed(() => (props.prefill.direction || 'IN') === 'IN')

const SOURCE_TYPES = ['自有资金', '银行流贷', '金租融资', '租金收入', '调配', '调配归还', '还款']
  .map((v) => ({ label: v, value: v }))

const form = ref({
  source_type: props.prefill.source_type || '自有资金',
  amount: null as number | null,
  transaction_date: Date.now() as number | null,
  note: '',
})

async function submit() {
  if (!form.value.amount || form.value.amount <= 0) { msg.warning('请填写金额（需大于 0）'); return }
  if (!form.value.transaction_date) { msg.warning('请选择日期'); return }
  submitting.value = true
  try {
    await http.post('/capital/transactions', {
      project_id: props.projectId,
      source_type: form.value.source_type,
      direction: isIn.value ? 'IN' : 'OUT',
      amount: form.value.amount,
      transaction_date: tsToYmd(form.value.transaction_date) || null,
      note: form.value.note || null,
    })
    msg.success(isIn.value ? '入金已登记' : '出金已登记')
    emit('success')
  } catch (e: any) { msg.error(errMsg(e)) } finally { submitting.value = false }
}
</script>

<template>
  <div>
    <n-form-item :label="isIn ? '来源类型' : '资金类型'" required>
      <n-select v-model:value="form.source_type" :options="SOURCE_TYPES" />
    </n-form-item>
    <n-form-item label="金额" required>
      <n-input-number
        v-model:value="form.amount" :min="0.01" :show-button="false" placeholder="金额（元）" style="width:100%"
      />
    </n-form-item>
    <n-form-item label="日期" required>
      <n-date-picker v-model:value="form.transaction_date" type="date" style="width:100%" />
    </n-form-item>
    <n-form-item label="备注">
      <n-input v-model:value="form.note" type="textarea" :rows="2" placeholder="选填" />
    </n-form-item>
    <n-button type="primary" block :loading="submitting" @click="submit">
      {{ isIn ? '确认入金' : '确认出金' }}
    </n-button>
  </div>
</template>
