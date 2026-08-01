<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import {
  NButton, NDataTable, NDescriptions, NDescriptionsItem, NDrawer, NDrawerContent, NEmpty,
  NForm, NFormItem, NIcon, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace,
  NTabPane, NTabs, NTag, NUpload, useMessage,
} from 'naive-ui'
import { Eye, Pencil, Plus, Trash2 } from 'lucide-vue-next'
import * as R from '../composables/useResource'
import { money, statusTagType } from '../utils/format'
import { api } from '../api/client'
import type { CrudConfig, DetailAction } from '../config/modules'

const props = defineProps<{ config: CrudConfig }>()
const msg = useMessage()
const items = ref<any[]>([])
const loading = ref(false)
const showModal = ref(false)
const editing = ref<any | null>(null)
const form = reactive<Record<string, any>>({})
const searchTerm = ref('')

// 详情抽屉
const showDetail = ref(false)
const detailRow = ref<any | null>(null)
const tabData = ref<Record<string, any[]>>({})

// 业务操作弹窗
const showActionModal = ref(false)
const activeAction = ref<DetailAction | null>(null)
const actionForm = reactive<Record<string, any>>({})

function blankForm() {
  props.config.fields.forEach((f) => { form[f.key] = f.type === 'number' ? null : '' })
}
async function refresh() {
  loading.value = true
  try {
    const d = await R.listRes(props.config.apiPath)
    items.value = d.items
  } catch { msg.error('加载失败') }
  finally { loading.value = false }
}
onMounted(refresh)
watch(() => props.config.apiPath, () => { items.value = []; searchTerm.value = ''; refresh() })

// 搜索过滤
const filteredItems = computed(() => {
  if (!searchTerm.value.trim()) return items.value
  const t = searchTerm.value.toLowerCase()
  return items.value.filter(item =>
    props.config.columns.some(k => String(item[k] ?? '').toLowerCase().includes(t))
  )
})

function openCreate() { editing.value = null; blankForm(); showModal.value = true }
function openEdit(row: any) {
  editing.value = row
  props.config.fields.forEach((f) => { form[f.key] = row[f.key] ?? (f.type === 'number' ? null : '') })
  showModal.value = true
}
async function openDetail(row: any) {
  detailRow.value = row
  showDetail.value = true
  tabData.value = {}
  // 拉关联子表
  if (props.config.detailTabs?.length) {
    for (const tab of props.config.detailTabs) {
      try {
        const params = tab.paramKey ? { [tab.paramKey]: row.id } : {}
        const { data } = await api.get(tab.endpoint, { params })
        tabData.value[tab.label] = data.items || []
      } catch { tabData.value[tab.label] = [] }
    }
  }
}
async function submit() {
  try {
    if (editing.value) await R.updateRes(props.config.apiPath, editing.value.id, { ...form })
    else await R.createRes(props.config.apiPath, { ...form })
    showModal.value = false; msg.success('已保存'); await refresh()
  } catch (e: any) {
    const det = e.response?.data?.detail
    msg.error(typeof det === 'string' ? det : det?.message || '保存失败')
  }
}
async function del(row: any) {
  try { await R.deleteRes(props.config.apiPath, row.id); msg.success('已删除'); await refresh() }
  catch { msg.error('删除失败') }
}

// 文件上传
const uploadUrl = computed(() => `/api/files/${props.config.uploadEntity}/${detailRow.value?.id}/upload`)
const uploadHeaders = computed(() => ({ Authorization: `Bearer ${localStorage.getItem('token') || ''}` }))
function onUploadFinish({ event }: any) {
  try {
    const resp = JSON.parse(event?.target?.response || '{}')
    if (detailRow.value) detailRow.value.file_path = resp.stored || resp.filename || ''
    msg.success(`上传成功: ${resp.filename || ''}`)
    refresh()
  } catch { msg.success('上传成功') }
}
async function downloadFile() {
  if (!detailRow.value?.id) return
  try {
    const resp = await api.get(`/files/${props.config.uploadEntity}/${detailRow.value.id}/file`, { responseType: 'blob' })
    const url = URL.createObjectURL(resp.data as unknown as Blob)
    const a = document.createElement('a')
    a.href = url; a.download = (detailRow.value.file_path || 'download') as string; a.click()
    URL.revokeObjectURL(url)
  } catch { msg.error('下载失败：可能无附件') }
}

// 业务操作（detailActions）
const visibleActions = computed(() =>
  (props.config.detailActions || []).filter(a => !a.showWhen || a.showWhen(detailRow.value))
)
function triggerAction(act: DetailAction) {
  activeAction.value = act
  act.fields?.forEach(f => { actionForm[f.key] = '' })
  if (act.fields?.length) { showActionModal.value = true } else { submitAction() }
}
async function submitAction() {
  if (!activeAction.value || !detailRow.value) return
  const act = activeAction.value
  try {
    const url = `${act.endpoint}/${detailRow.value.id}${act.action}`
    if (act.method === 'PATCH') await api.patch(url, { ...actionForm })
    else await api.post(url, { ...actionForm })
    msg.success(act.successMsg || '操作成功')
    showActionModal.value = false
    await refresh()
    const updated = items.value.find((i: any) => i.id === detailRow.value?.id)
    if (updated) detailRow.value = updated
  } catch (e: any) {
    msg.error(e.response?.data?.detail?.message || e.response?.data?.detail || '操作失败')
  }
}

// Excel 导入/导出
function onImportFinish({ event }: any) {
  try {
    const r = JSON.parse(event?.target?.response || '{}')
    msg.success(`导入成功: ${r.imported ?? 0} 条`)
    refresh()
  } catch { msg.error('导入失败') }
}
async function exportData() {
  try {
    const key = props.config.uploadEntity || props.config.apiPath.slice(1)
    const resp = await api.get(`/excel/export/${key}`, { responseType: 'blob' })
    const url = URL.createObjectURL(resp.data as unknown as Blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${props.config.title}.xlsx`; a.click()
    URL.revokeObjectURL(url)
    msg.success('导出成功')
  } catch { msg.error('导出失败') }
}

// 表格列
const tagKeys = computed(() => new Set(props.config.tagKeys || []))
const numKeys = computed(() => new Set(props.config.numKeys || []))
const allFields = computed(() => props.config.columns.map(k => ({ key: k, label: props.config.labels?.[k] ?? k })))
const tableColumns = computed(() => {
  const base = props.config.columns.map(key => {
    const col: any = { title: props.config.labels?.[key] ?? key, key }
    if (tagKeys.value.has(key)) {
      col.render = (row: any) => row[key] != null
        ? h(NTag, { size: 'small', type: statusTagType(row[key]) as any, bordered: false }, () => row[key])
        : '-'
    } else if (numKeys.value.has(key)) {
      col.align = 'right'; col.className = 'num'
      col.render = (row: any) => h('span', { class: 'num' }, money(row[key]))
    }
    return col
  })
  base.push({
    title: '操作', key: '__op', width: 140, align: 'center',
    render: (row: any) => h(NSpace, { size: 4, justify: 'center' }, () => [
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => openDetail(row), title: '详情' },
        { icon: () => h(NIcon, null, { default: () => h(Eye, { size: 14 }) }) }),
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => openEdit(row), title: '编辑' },
        { icon: () => h(NIcon, null, { default: () => h(Pencil, { size: 14 }) }) }),
      h(NPopconfirm, { onPositiveClick: () => del(row) }, {
        trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error', title: '删除' },
          { icon: () => h(NIcon, null, { default: () => h(Trash2, { size: 14 }) }) }),
        default: () => '确认删除？',
      }),
    ]),
  })
  return base
})
</script>

<template>
  <div class="crud">
    <div class="crud-head">
      <div>
        <h3>{{ config.title }}</h3>
        <div class="muted tiny">共 {{ items.length }} 条</div>
      </div>
      <n-space align="center">
        <n-upload v-if="config.importable" :action="`/api/excel/import/${config.apiPath.slice(1)}`" :headers="uploadHeaders" :show-file-list="false" accept=".xlsx,.xls" @finish="onImportFinish">
          <n-button size="small" quaternary>导入Excel</n-button>
        </n-upload>
        <n-button size="small" quaternary @click="exportData">导出</n-button>
        <n-input v-model:value="searchTerm" placeholder="搜索..." size="small" style="width:180px" clearable />
        <n-button v-if="config.creatable !== false" type="primary" @click="openCreate">
          <template #icon><n-icon :component="Plus" /></template>新增
        </n-button>
      </n-space>
    </div>

    <div class="card table-wrap">
      <n-data-table :columns="tableColumns" :data="filteredItems" :loading="loading"
        :pagination="{ pageSize: 10 }" :bordered="false" size="small" striped>
        <template #empty><n-empty description="暂无数据" style="padding:32px 0" /></template>
      </n-data-table>
    </div>

    <!-- 新增/编辑 -->
    <n-modal v-model:show="showModal" preset="card" :title="editing ? '编辑' : '新增'" style="width:520px;max-width:94vw">
      <n-form label-placement="left" :label-width="140">
        <n-form-item v-for="f in config.fields" :key="f.key" :label="f.label">
          <n-select v-if="f.type === 'select'" v-model:value="form[f.key]" :options="f.options" />
          <n-input-number v-else-if="f.type === 'number'" v-model:value="form[f.key]" style="width:100%" />
          <n-input v-else v-model:value="form[f.key]" :placeholder="f.type === 'date' ? 'YYYY-MM-DD' : ''" />
        </n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showModal = false">取消</n-button><n-button type="primary" @click="submit">保存</n-button></n-space></template>
    </n-modal>

    <!-- 详情抽屉 -->
    <n-drawer v-model:show="showDetail" :width="520" placement="right">
      <n-drawer-content :title="config.title + ' 详情'" closable>
        <n-descriptions v-if="detailRow" label-placement="left" bordered :column="1" size="small">
          <n-descriptions-item v-for="f in allFields" :key="f.key" :label="f.label">
            <span v-if="numKeys.has(f.key)" class="num">{{ money(detailRow[f.key]) }}</span>
            <n-tag v-else-if="tagKeys.has(f.key)" size="small" :type="statusTagType(detailRow[f.key]) as any" bordered="false">{{ detailRow[f.key] ?? '-' }}</n-tag>
            <span v-else>{{ detailRow[f.key] ?? '-' }}</span>
          </n-descriptions-item>
        </n-descriptions>

        <!-- 文件上传 -->
        <div v-if="config.fileUpload && detailRow" style="margin-top:20px">
          <div class="muted" style="margin-bottom:8px;font-weight:600">附件管理</div>
          <div v-if="detailRow.file_path" style="margin-bottom:8px">
            <n-tag size="small" type="success" bordered="false">{{ String(detailRow.file_path).slice(0, 30) }}</n-tag>
            <n-button size="small" quaternary @click="downloadFile" style="margin-left:8px">下载/预览</n-button>
          </div>
          <div v-else class="muted tiny" style="margin-bottom:8px">暂无附件</div>
          <n-upload :action="uploadUrl" :headers="uploadHeaders" accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.gif"
            :max="1" :show-file-list="false" @finish="onUploadFinish">
            <n-button size="small" dashed>上传附件（PDF/DOC/图片）</n-button>
          </n-upload>
        </div>

        <!-- 业务操作按钮 -->
        <div v-if="visibleActions.length" style="margin-top:20px">
          <div class="muted" style="margin-bottom:8px;font-weight:600">业务操作</div>
          <n-space>
            <n-button v-for="act in visibleActions" :key="act.label" type="primary" @click="triggerAction(act)">{{ act.label }}</n-button>
          </n-space>
        </div>

        <!-- 关联子表 -->
        <n-tabs v-if="config.detailTabs?.length" type="line" size="small" style="margin-top:20px">
          <n-tab-pane v-for="tab in config.detailTabs" :key="tab.label" :name="tab.label"
            :tab="`${tab.label} (${(tabData[tab.label] || []).length})`">
            <n-data-table
              :columns="tab.columns.map((k: string) => ({ title: tab.labels?.[k] ?? k, key: k }))"
              :data="tabData[tab.label] || []" :bordered="false" size="small" striped />
          </n-tab-pane>
        </n-tabs>
      </n-drawer-content>
    </n-drawer>

    <!-- 业务操作弹窗 -->
    <n-modal v-model:show="showActionModal" preset="card" :title="activeAction?.label || '操作'" style="width:340px">
      <n-form label-placement="left" :label-width="120">
        <n-form-item v-for="f in activeAction?.fields || []" :key="f.key" :label="f.label">
          <n-input v-model:value="actionForm[f.key]" placeholder="YYYY-MM-DD" />
        </n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showActionModal = false">取消</n-button><n-button type="primary" @click="submitAction">确认</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<style scoped>
.crud-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.table-wrap { padding: 4px; overflow: hidden; }
:deep(.n-data-table .n-data-table-th) { font-weight: 600; }
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
