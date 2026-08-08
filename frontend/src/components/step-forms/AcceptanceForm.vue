<script setup lang="ts">
import { ref } from 'vue'
import {
  NButton, NDatePicker, NFormItem, NInput, NInputNumber, NTag, useMessage,
} from 'naive-ui'
import { http } from '../../api/client'
import { errMsg } from '../../utils/errMsg'
import { tsToYmd } from '../../utils/format'

// 验收（acceptance）：链式 create → upload（可选）→ approve
// 每步失败显示该步中文错误并保留已完成子步骤状态，可直接重试
const props = defineProps<{ projectId: string; prefill: Record<string, any> }>()
const emit = defineEmits<{ (e: 'success'): void }>()
const msg = useMessage()

const form = ref({
  inspector: '',
  acceptance_date: Date.now() as number | null,
  quantity_accepted: null as number | null,
  quantity_rejected: 0,
  notes: '',
})
const file = ref<File | null>(null)

type SubState = 'pending' | 'doing' | 'done' | 'skip' | 'error'
const sub = ref<{ state: SubState; error: string }[]>([
  { state: 'pending', error: '' },
  { state: 'pending', error: '' },
  { state: 'pending', error: '' },
])
const arId = ref<string | null>(null)
const submitting = ref(false)

function onFileChange(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] || null
}

function fail(idx: number, e: any) {
  sub.value[idx].state = 'error'
  sub.value[idx].error = errMsg(e)
  msg.error(`${['创建验收单', '上传附件', '审批通过'][idx]}失败：${sub.value[idx].error}`)
}

async function submit() {
  if (form.value.quantity_accepted === null) { msg.warning('请填写验收数量'); return }
  submitting.value = true
  try {
    // 第 1 步：创建（重试时已创建则跳过）
    if (!arId.value) {
      sub.value[0] = { state: 'doing', error: '' }
      try {
        const { data } = await http.post('/acceptances', {
          project_id: props.projectId,
          acceptance_type: props.prefill.acceptance_type || '采购验收',
          inspector: form.value.inspector || null,
          acceptance_date: tsToYmd(form.value.acceptance_date) || null,
          quantity_accepted: form.value.quantity_accepted,
          quantity_rejected: form.value.quantity_rejected || 0,
          notes: form.value.notes || null,
        })
        arId.value = data.id
        sub.value[0].state = 'done'
      } catch (e: any) { fail(0, e); return }
    }
    // 第 2 步：上传附件（未选文件则跳过）
    if (sub.value[1].state !== 'done' && sub.value[1].state !== 'skip') {
      if (!file.value) {
        sub.value[1] = { state: 'skip', error: '' }
      } else {
        sub.value[1] = { state: 'doing', error: '' }
        try {
          const fd = new FormData()
          fd.append('file', file.value)
          await http.post(`/files/acceptances/${arId.value}/upload`, fd)
          sub.value[1].state = 'done'
        } catch (e: any) { fail(1, e); return }
      }
    }
    // 第 3 步：审批通过
    if (sub.value[2].state !== 'done') {
      sub.value[2] = { state: 'doing', error: '' }
      try {
        await http.post(`/acceptances/${arId.value}/approve`)
        sub.value[2].state = 'done'
      } catch (e: any) { fail(2, e); return }
    }
    msg.success('验收已通过')
    emit('success')
  } finally { submitting.value = false }
}

const SUB_LABELS = ['创建验收单', '上传附件', '审批通过']
const SUB_TAG: Record<SubState, { type: any; text: string }> = {
  pending: { type: 'default', text: '待执行' },
  doing: { type: 'info', text: '执行中' },
  done: { type: 'success', text: '已完成' },
  skip: { type: 'warning', text: '已跳过' },
  error: { type: 'error', text: '失败' },
}
</script>

<template>
  <div>
    <n-form-item label="验收类型">
      <n-input :value="prefill.acceptance_type || '采购验收'" disabled />
    </n-form-item>
    <n-form-item label="验收日期" required>
      <n-date-picker v-model:value="form.acceptance_date" type="date" style="width:100%" />
    </n-form-item>
    <n-form-item label="验收人">
      <n-input v-model:value="form.inspector" placeholder="选填" />
    </n-form-item>
    <n-form-item label="合格数量(台)" required>
      <n-input-number v-model:value="form.quantity_accepted" :min="0" style="width:100%" />
    </n-form-item>
    <n-form-item label="不合格数量(台)">
      <n-input-number v-model:value="form.quantity_rejected" :min="0" style="width:100%" />
    </n-form-item>
    <n-form-item label="备注">
      <n-input v-model:value="form.notes" type="textarea" :rows="2" placeholder="选填" />
    </n-form-item>
    <n-form-item label="验收附件（选填）">
      <input type="file" accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.gif" @change="onFileChange" />
    </n-form-item>

    <!-- 子步骤状态 -->
    <div v-if="arId || sub.some((s) => s.state !== 'pending')" class="sub-steps">
      <div v-for="(s, i) in sub" :key="i" class="sub-step">
        <span>{{ SUB_LABELS[i] }}</span>
        <n-tag size="small" :type="SUB_TAG[s.state].type" :bordered="false">{{ SUB_TAG[s.state].text }}</n-tag>
        <span v-if="s.error" class="sub-error">{{ s.error }}</span>
      </div>
    </div>

    <n-button type="primary" block :loading="submitting" @click="submit">
      {{ sub.some((s) => s.state === 'error') ? '重试' : '提交验收' }}
    </n-button>
  </div>
</template>

<style scoped>
.sub-steps { margin: 4px 0 12px; padding: 10px 12px; background: #F8FAFC; border-radius: 6px; }
.sub-step { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 13px; flex-wrap: wrap; }
.sub-error { color: #DC2626; font-size: 12px; width: 100%; }
</style>
