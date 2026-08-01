<script setup lang="ts">
import { computed } from 'vue'
import { NDrawer, NDrawerContent, NEmpty, useMessage } from 'naive-ui'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'
import CapitalForm from './step-forms/CapitalForm.vue'
import AcceptanceForm from './step-forms/AcceptanceForm.vue'
import BillingForm from './step-forms/BillingForm.vue'
import ConfirmationForm from './step-forms/ConfirmationForm.vue'
import InvoiceForm from './step-forms/InvoiceForm.vue'

const props = defineProps<{ show: boolean; projectId: string; step: any }>()
const emit = defineEmits<{ (e: 'update:show', v: boolean): void; (e: 'done'): void }>()
const msg = useMessage()

// 注册表模式：drawer_schema → 子表单组件（capital_in / capital_out 共用一个表单）
const registry: Record<string, any> = {
  capital_in: CapitalForm,
  capital_out: CapitalForm,
  acceptance: AcceptanceForm,
  billing_confirm: BillingForm,
  confirmation: ConfirmationForm,
  invoice_issue: InvoiceForm,
}

const activeComp = computed(() => registry[props.step?.drawer_schema] || null)

// 预填：{{project_id}} 替换为当前项目 id，其余字面值直接填入
const prefill = computed(() => {
  const out: Record<string, any> = {}
  for (const [k, v] of Object.entries(props.step?.prefill || {})) {
    out[k] = v === '{{project_id}}' ? props.projectId : v
  }
  return out
})

const showModel = computed({
  get: () => props.show,
  set: (v: boolean) => emit('update:show', v),
})

async function onSuccess() {
  // 提交成功后刷新工作流进度，再通知父组件 reload
  try {
    await http.post(`/workflows/${props.projectId}/refresh`)
  } catch (e: any) { msg.warning(errMsg(e)) }
  showModel.value = false
  emit('done')
}
</script>

<template>
  <n-drawer v-model:show="showModel" :width="480" placement="right">
    <n-drawer-content :title="step ? `Step ${step.seq} — ${step.name}` : ''" closable>
      <component
        :is="activeComp"
        v-if="activeComp"
        :key="step?.seq"
        :project-id="projectId"
        :prefill="prefill"
        @success="onSuccess"
      />
      <n-empty v-else description="暂不支持该步骤类型" />
    </n-drawer-content>
  </n-drawer>
</template>
