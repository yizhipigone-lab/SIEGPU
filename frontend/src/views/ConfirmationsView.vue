<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { NButton, NDataTable, NFormItem, NInput, NModal, NSpace, NTag, useMessage } from 'naive-ui'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { statusTagType } from '../utils/format'
import EmptyState from '../components/EmptyState.vue'

interface Confirmation {
  id: string; billing_id: string; sales_order_id: string
  period_label: string; status: string
  confirmed_by_customer: string | null; confirmed_at: string | null
  created_at: string
}

const msg = useMessage()
const items = ref<Confirmation[]>([])
const loading = ref(false)

// 确认弹窗（客户签字人）
const confirmTarget = ref<Confirmation | null>(null)
const confirmName = ref('')
const showConfirm = computed({
  get: () => !!confirmTarget.value,
  set: (v: boolean) => { if (!v) { confirmTarget.value = null; confirmName.value = '' } },
})

// 争议弹窗
const disputeTarget = ref<Confirmation | null>(null)
const disputeReason = ref('')
const showDispute = computed({
  get: () => !!disputeTarget.value,
  set: (v: boolean) => { if (!v) { disputeTarget.value = null; disputeReason.value = '' } },
})

function openConfirm(row: Confirmation) { confirmTarget.value = row; confirmName.value = '' }
function openDispute(row: Confirmation) { disputeTarget.value = row; disputeReason.value = '' }

async function submitConfirm() {
  if (!confirmTarget.value) return
  if (!confirmName.value.trim()) { msg.warning('请填客户签字人'); return }
  try {
    await http.post(`/confirmations/${confirmTarget.value.id}/confirm`, null, {
      params: { confirmed_by_customer: confirmName.value },
    })
    msg.success('已确认')
    confirmTarget.value = null; confirmName.value = ''
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

async function submitDispute() {
  if (!disputeTarget.value) return
  if (!disputeReason.value.trim()) { msg.warning('请填争议原因'); return }
  try {
    await http.post(`/confirmations/${disputeTarget.value.id}/dispute`, null, {
      params: { reason: disputeReason.value },
    })
    msg.success('已标记争议')
    disputeTarget.value = null; disputeReason.value = ''
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}

const columns = [
  { title: '计费期', key: 'period_label', width: 100 },
  { title: '状态', key: 'status', width: 90, render: (r: any) => h(NTag, { type: statusTagType(r.status) as any, size: 'small' }, () => r.status) },
  { title: '客户签字人', key: 'confirmed_by_customer', width: 140 },
  { title: '确认日期', key: 'confirmed_at', width: 110 },
  { title: '争议原因', key: 'dispute_reason', render: (r: any) => r.dispute_reason || '—' },
  { title: '操作', key: '__op', width: 130, render: (r: Confirmation) =>
      r.status === '待确认'
        ? h(NSpace, { size: 4 }, () => [
            h(NButton, { size: 'tiny', type: 'primary', quaternary: true, onClick: () => openConfirm(r) }, () => '确认'),
            h(NButton, { size: 'tiny', type: 'error', quaternary: true, onClick: () => openDispute(r) }, () => '争议'),
          ])
        : null },
]

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/confirmations')
    items.value = data
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">客户确认单</h2>
    </div>
    <n-dataTable :columns="columns" :data="items" :loading="loading" :bordered="false">
      <template #empty>
        <EmptyState description="还没有客户确认单，交付流程走到「客户确认」并签字后，确认记录会显示在这里" />
      </template>
    </n-dataTable>

    <!-- 客户确认 -->
    <n-modal v-model:show="showConfirm" preset="card" title="客户确认" style="width:380px">
      <n-form-item label="客户签字人">
        <n-input v-model:value="confirmName" placeholder="必填" />
      </n-form-item>
      <template #footer>
        <n-space justify="end">
          <n-button @click="confirmTarget = null">取消</n-button>
          <n-button type="primary" @click="submitConfirm">确认</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 标记争议 -->
    <n-modal v-model:show="showDispute" preset="card" title="标记争议" style="width:380px">
      <n-form-item label="争议原因">
        <n-input v-model:value="disputeReason" type="textarea" :rows="2" placeholder="必填" />
      </n-form-item>
      <template #footer>
        <n-space justify="end">
          <n-button @click="disputeTarget = null">取消</n-button>
          <n-button type="error" @click="submitDispute">确认争议</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
