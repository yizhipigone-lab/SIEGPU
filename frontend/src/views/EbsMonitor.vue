<script setup lang="ts">
// EBS 同步监控（二期 W1-2）：字段映射配置 + 手动触发出站 + 同步日志/失败重试 + 统计。
// Mock 期出站仅 SIEGPU→EBS；映射直接/constant 生效，date_format/decimal_scale 期外实现。
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NFormItem, NInput, NModal, NSelect, NSpace, NStatistic, NTag, useMessage,
} from 'naive-ui'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'
import EmptyState from '../components/EmptyState.vue'

const msg = useMessage()

// 10 类业务域（父计划 §3.1）
const ENTITY_TYPES = [
  { label: '客户', value: 'customer' },
  { label: '供应商', value: 'supplier' },
  { label: '合同', value: 'contract' },
  { label: '发票', value: 'invoice' },
  { label: '资产', value: 'asset' },
  { label: '资金收付', value: 'payment' },
  { label: '预付款(设备)', value: 'prepayment' },
  { label: '金租放款', value: 'lease_disbursement' },
  { label: '还款', value: 'repayment' },
  { label: '采购入库', value: 'goods_receipt' },
]
const TRANSFORM_RULES = [
  { label: 'direct（直接重命名）', value: 'direct' },
  { label: 'constant（字面量）', value: 'constant' },
  { label: 'date_format（期外）', value: 'date_format' },
  { label: 'decimal_scale（期外）', value: 'decimal_scale' },
]
const SYNC_TYPES = [
  { label: 'create', value: 'create' },
  { label: 'update', value: 'update' },
  { label: 'delete', value: 'delete' },
]
const entityLabel = (t: string) => ENTITY_TYPES.find((x) => x.value === t)?.label || t

// ------------------------------ 字段映射 ------------------------------
interface Mapping {
  id: string; entity_type: string; siegpu_field: string; ebs_field: string
  transform_rule: string; transform_config: Record<string, unknown> | null
}
const mappings = ref<Mapping[]>([])
const mappingsLoading = ref(false)

const showMapping = ref(false)
const editing = ref<Mapping | null>(null)
const mEntityType = ref<string | null>(null)
const mSiegpu = ref('')
const mEbs = ref('')
const mRule = ref('direct')
const mConfigText = ref('') // transform_config 的 JSON 文本（可选）

function openCreateMapping() {
  editing.value = null
  mEntityType.value = null; mSiegpu.value = ''; mEbs.value = ''; mRule.value = 'direct'; mConfigText.value = ''
  showMapping.value = true
}
function openEditMapping(row: Mapping) {
  editing.value = row
  mEntityType.value = row.entity_type; mSiegpu.value = row.siegpu_field; mEbs.value = row.ebs_field
  mRule.value = row.transform_rule; mConfigText.value = row.transform_config ? JSON.stringify(row.transform_config) : ''
  showMapping.value = true
}

async function submitMapping() {
  if (!mEntityType.value) { msg.warning('请选实体类型'); return }
  if (!mSiegpu.value.trim() || !mEbs.value.trim()) { msg.warning('SIEGPU 字段 / EBS 字段必填'); return }
  let config: Record<string, unknown> | null = null
  if (mConfigText.value.trim()) {
    try { config = JSON.parse(mConfigText.value) } catch { msg.error('transform_config 不是合法 JSON'); return }
  }
  const body = { entity_type: mEntityType.value, siegpu_field: mSiegpu.value.trim(), ebs_field: mEbs.value.trim(), transform_rule: mRule.value, transform_config: config }
  try {
    if (editing.value) {
      await http.patch(`/ebs/mappings/${editing.value.id}`, { ebs_field: body.ebs_field, transform_rule: body.transform_rule, transform_config: body.transform_config })
      msg.success('已更新')
    } else {
      await http.post('/ebs/mappings', body)
      msg.success('已新增')
    }
    showMapping.value = false
    await loadMappings()
  } catch (e: unknown) { msg.error(errMsg(e as Error)) }
}

async function deleteMapping(row: Mapping) {
  try {
    await http.delete(`/ebs/mappings/${row.id}`)
    msg.success('已删除')
    await loadMappings()
  } catch (e: unknown) { msg.error(errMsg(e as Error)) }
}

const mappingColumns = [
  { title: '实体类型', key: 'entity_type', width: 120, render: (r: Mapping) => entityLabel(r.entity_type) },
  { title: 'SIEGPU 字段', key: 'siegpu_field' },
  { title: 'EBS 字段', key: 'ebs_field' },
  { title: '转换规则', key: 'transform_rule', width: 130 },
  { title: '操作', key: '__op', width: 130, render: (r: Mapping) =>
      h(NSpace, { size: 4 }, () => [
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => openEditMapping(r) }, () => '编辑'),
        h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => deleteMapping(r) }, () => '删除'),
      ]) },
]

async function loadMappings() {
  mappingsLoading.value = true
  try { const { data } = await http.get('/ebs/mappings'); mappings.value = data.items || [] }
  catch (e: unknown) { msg.error(errMsg(e as Error)) }
  finally { mappingsLoading.value = false }
}

// ------------------------------ 手动触发 ------------------------------
const tEntityType = ref<string | null>('customer')
const tEntityId = ref('')
const tSyncType = ref('create')
const triggering = ref(false)
const lastResult = ref<Record<string, unknown> | null>(null)

async function triggerSync() {
  if (!tEntityType.value) { msg.warning('请选实体类型'); return }
  if (!tEntityId.value.trim()) { msg.warning('请填实体 ID'); return }
  triggering.value = true
  try {
    const { data } = await http.post(`/ebs/sync/${tEntityType.value}/${tEntityId.value.trim()}`, { sync_type: tSyncType.value })
    lastResult.value = data
    msg.success('同步完成')
    await loadLogs()
  } catch (e: unknown) { msg.error(errMsg(e as Error)) }
  finally { triggering.value = false }
}

// ------------------------------ 同步日志 ------------------------------
interface SyncLog {
  id: string; entity_type: string; entity_id: string; entity_version: string
  direction: string; sync_type: string; status: string; ebs_reference: string | null
  request_payload: Record<string, unknown> | null; response_payload: Record<string, unknown> | null
  error_message: string | null; retry_count: number; synced_at: string | null; skipped: boolean
}
const logs = ref<SyncLog[]>([])
const logsLoading = ref(false)
const logStatusFilter = ref<string | null>(null)

function statusTagType(s: string): 'success' | 'error' | 'warning' | 'default' {
  if (s === 'MOCK_SUCCESS' || s === 'SUCCESS') return 'success'
  if (s === 'FAILED') return 'error'
  return 'default'
}

async function loadLogs() {
  logsLoading.value = true
  try {
    const params: Record<string, string> = {}
    if (logStatusFilter.value) params.status = logStatusFilter.value
    const { data } = await http.get('/ebs/logs', { params })
    logs.value = data.items || []
  } catch (e: unknown) { msg.error(errMsg(e as Error)) }
  finally { logsLoading.value = false }
}

async function retry(row: SyncLog) {
  try {
    await http.post(`/ebs/logs/${row.id}/retry`)
    msg.success('已重试')
    await loadLogs()
  } catch (e: unknown) { msg.error(errMsg(e as Error)) }
}

const logColumns = [
  { title: '实体', key: 'entity_type', width: 110, render: (r: SyncLog) => entityLabel(r.entity_type) },
  { title: '实体ID', key: 'entity_id', width: 150, ellipsis: { tooltip: true }, render: (r: SyncLog) => r.entity_id.slice(0, 8) + '…' },
  { title: '类型', key: 'sync_type', width: 80 },
  { title: '状态', key: 'status', width: 120, render: (r: SyncLog) =>
      h(NSpace, { size: 4, align: 'center' }, () => [
        h(NTag, { type: statusTagType(r.status), size: 'small' }, () => r.status),
        r.skipped ? h(NTag, { size: 'small', type: 'default' }, () => '幂等跳过') : null,
      ]) },
  { title: 'EBS 回执', key: 'ebs_reference', width: 180, ellipsis: { tooltip: true }, render: (r: SyncLog) => r.ebs_reference || '—' },
  { title: '版本', key: 'entity_version', width: 120, render: (r: SyncLog) => r.entity_version.slice(0, 12) },
  { title: '同步时间', key: 'synced_at', width: 160, render: (r: SyncLog) => r.synced_at?.replace('T', ' ').slice(0, 19) || '—' },
  { title: '操作', key: '__op', width: 90, render: (r: SyncLog) =>
      r.status === 'FAILED'
        ? h(NButton, { size: 'tiny', quaternary: true, type: 'warning', onClick: () => retry(r) }, () => '重试')
        : null },
]

// ------------------------------ 统计 ------------------------------
const stats = computed(() => {
  const total = logs.value.length
  const ok = logs.value.filter((l) => l.status === 'MOCK_SUCCESS' || l.status === 'SUCCESS').length
  const failed = logs.value.filter((l) => l.status === 'FAILED').length
  return { total, ok, failed }
})

onMounted(() => { loadMappings(); loadLogs() })
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">EBS 同步监控</h2>
      <n-tag :bordered="false" type="info" size="small">Mock 模式 · 仅出站 SIEGPU→EBS</n-tag>
    </div>

    <!-- 统计 -->
    <n-space :size="16" style="margin-bottom:16px">
      <n-card size="small" style="flex:1;min-width:140px">
        <n-statistic label="同步记录（近 100）" :value="stats.total" />
      </n-card>
      <n-card size="small" style="flex:1;min-width:140px">
        <n-statistic label="成功" :value="stats.ok" />
      </n-card>
      <n-card size="small" style="flex:1;min-width:140px">
        <n-statistic label="失败" :value="stats.failed" />
      </n-card>
    </n-space>

    <!-- 字段映射配置 -->
    <n-card title="字段映射配置" size="small" style="margin-bottom:16px">
      <template #header-extra>
        <n-button size="small" type="primary" @click="openCreateMapping">新增映射</n-button>
      </template>
      <n-data-table :columns="mappingColumns" :data="mappings" :loading="mappingsLoading" :bordered="false" :max-height="240">
        <template #empty>
          <EmptyState description="未配置字段映射。无映射时按原字段出站；配置后 SIEGPU 字段会重命名/转换为 EBS 字段" />
        </template>
      </n-data-table>
    </n-card>

    <!-- 手动触发 -->
    <n-card title="手动触发同步" size="small" style="margin-bottom:16px">
      <n-space align="center" :wrap="false">
        <n-form-item label="实体类型" :show-feedback="false" style="margin:0">
          <n-select v-model:value="tEntityType" :options="ENTITY_TYPES" style="width:160px" />
        </n-form-item>
        <n-form-item label="实体 ID" :show-feedback="false" style="margin:0">
          <n-input v-model:value="tEntityId" placeholder="粘贴 UUID" style="width:300px" />
        </n-form-item>
        <n-form-item label="操作" :show-feedback="false" style="margin:0">
          <n-select v-model:value="tSyncType" :options="SYNC_TYPES" style="width:120px" />
        </n-form-item>
        <n-button type="primary" :loading="triggering" @click="triggerSync">同步</n-button>
      </n-space>
      <div v-if="lastResult" style="margin-top:12px;padding:10px 12px;background:var(--c-bg);border-radius:6px;font-size:13px">
        <span>结果：</span>
        <n-tag size="small" :type="statusTagType(String(lastResult.status))">{{ lastResult.status }}</n-tag>
        <span style="margin-left:8px;color:var(--c-text-light,#999)">{{ lastResult.ebs_reference || '—' }}</span>
        <span v-if="lastResult.skipped" style="margin-left:8px;color:var(--c-warning,#d97706)">（幂等跳过：同版本已同步）</span>
      </div>
    </n-card>

    <!-- 同步日志 -->
    <n-card title="同步日志" size="small">
      <template #header-extra>
        <n-select
          v-model:value="logStatusFilter" :options="[{label:'全部',value:null},{label:'成功',value:'MOCK_SUCCESS'},{label:'失败',value:'FAILED'}]"
          size="small" style="width:120px" @update:value="loadLogs"
        />
      </template>
      <n-data-table :columns="logColumns" :data="logs" :loading="logsLoading" :bordered="false" :max-height="360">
        <template #empty>
          <EmptyState description="还没有同步记录。在上方「手动触发」选实体并同步，记录会显示在这里" />
        </template>
      </n-data-table>
    </n-card>

    <!-- 新增/编辑映射 -->
    <n-modal v-model:show="showMapping" preset="card" :title="editing ? '编辑映射' : '新增映射'" style="width:480px">
      <n-form-item label="实体类型">
        <n-select v-model:value="mEntityType" :options="ENTITY_TYPES" :disabled="!!editing" placeholder="必选" />
      </n-form-item>
      <n-form-item label="SIEGPU 字段">
        <n-input v-model:value="mSiegpu" :disabled="!!editing" placeholder="如 name" />
      </n-form-item>
      <n-form-item label="EBS 字段">
        <n-input v-model:value="mEbs" placeholder="如 CUSTOMER_NAME" />
      </n-form-item>
      <n-form-item label="转换规则">
        <n-select v-model:value="mRule" :options="TRANSFORM_RULES" />
      </n-form-item>
      <n-form-item label="transform_config（可选 JSON）">
        <n-input v-model:value="mConfigText" type="textarea" :rows="2" placeholder='constant 规则填 {"value":"SIEGPU"}' />
      </n-form-item>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showMapping = false">取消</n-button>
          <n-button type="primary" @click="submitMapping">{{ editing ? '保存' : '新增' }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
