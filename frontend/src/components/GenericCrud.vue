<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NDataTable, NDatePicker, NDescriptions, NDescriptionsItem, NDrawer, NDrawerContent, NEmpty,
  NAlert, NDivider, NForm, NFormItem, NIcon, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace,
  NTabPane, NTabs, NTag, NTooltip, NUpload, useMessage,
} from 'naive-ui'
import { Eye, FileText, HelpCircle, Pencil, Plus, Trash2, Workflow } from 'lucide-vue-next'
import * as R from '../composables/useResource'
import { money, statusTagType, tsToYmd, ymdToTs } from '../utils/format'
import { errMsg } from '../utils/errMsg'
import { api } from '../api/client'
import type { CrudConfig, DetailAction, FieldConfig } from '../config/modules'
import WorkflowProgress from './WorkflowProgress.vue'

const props = defineProps<{ config: CrudConfig }>()
const msg = useMessage()
const route = useRoute()
const router = useRouter()
const items = ref<any[]>([])
const loading = ref(false)
const showModal = ref(false)
const editing = ref<any | null>(null)
const form = reactive<Record<string, any>>({})
// 即时校验：字段有 validate 时返回警告文案（模板里 :status 标黄 + 下方 ⚠ 提示），undefined 即通过。
// 非阻断式（不拦保存），与 ProfitView 百分比兜底一致；真正非法值仍由后端拒绝。
function fieldWarn(f: FieldConfig): string | undefined {
  return typeof f.validate === 'function' ? f.validate(form[f.key]) : undefined
}
const searchTerm = ref('')

// 远程下拉选项缓存：fieldKey → options
const remoteOpts = reactive<Record<string, { label: string; value: string }[]>>({})
async function loadRemoteOptions() {
  for (const f of props.config.fields) {
    if (!f.remoteOptions) continue
    const { endpoint, label, value, tags } = f.remoteOptions
    const endpoints = Array.isArray(endpoint) ? endpoint : [endpoint]
    try {
      const resps = await Promise.all(endpoints.map((ep) => api.get(ep)))
      remoteOpts[f.key] = resps.flatMap((r, i) =>
        (r.data.items || r.data || []).map((it: any) => ({
          label: `${tags?.[i] ? `[${tags[i]}] ` : ''}${it[label]}`, value: it[value],
        })))
    } catch { remoteOpts[f.key] = [] }
  }
}

// 详情抽屉
const showDetail = ref(false)
const detailRow = ref<any | null>(null)
const tabData = ref<Record<string, any[]>>({})
const stages = ref<any[]>([])

// 业务操作弹窗
const showActionModal = ref(false)
const activeAction = ref<DetailAction | null>(null)
const actionForm = reactive<Record<string, any>>({})

function blankForm() {
  // select 默认 null（非 ''）：'' 会被后端 Literal 枚举拒绝（如合同判定三字段）
  props.config.fields.forEach((f) => { form[f.key] = (f.type === 'number' || f.type === 'select') ? null : '' })
}
async function refresh() {
  loading.value = true
  try {
    const d = await R.listRes(props.config.apiPath)
    items.value = d.items
  } catch { msg.error('加载失败') }
  finally { loading.value = false }
}
onMounted(() => { refresh(); loadRemoteOptions() })
watch(() => props.config.apiPath, () => { items.value = []; searchTerm.value = ''; refresh(); loadRemoteOptions() })

// 搜索过滤
const filteredItems = computed(() => {
  if (!searchTerm.value.trim()) return items.value
  const t = searchTerm.value.toLowerCase()
  return items.value.filter(item =>
    props.config.columns.some(k => String(item[k] ?? '').toLowerCase().includes(t))
  )
})

function openCreate() {
  editing.value = null; blankForm()
  // 工作台跳转带 ?project_id= 时预填项目字段
  const qpid = route.query.project_id as string
  if (qpid && props.config.fields.some((f) => f.key === 'project_id')) form.project_id = qpid
  showModal.value = true
}
function openEdit(row: any) {
  editing.value = row
  props.config.fields.forEach((f) => { form[f.key] = row[f.key] ?? ((f.type === 'number' || f.type === 'select') ? null : '') })
  showModal.value = true
}
async function openDetail(row: any) {
  detailRow.value = row
  showDetail.value = true
  tabData.value = {}
  stages.value = []
  // 交付阶段（stageFlow 模块：拉详情里的 stages）
  if (props.config.stageFlow) await loadStages(row.id)
  await loadTabs(row.id)
}
async function loadTabs(rowId: string) {
  // 拉关联子表（业务操作成功后也会重拉，防 tab 展示操作前旧数据——W9-10 变更记录实测踩中）
  if (!props.config.detailTabs?.length) return
  for (const tab of props.config.detailTabs) {
    try {
      const params = tab.paramKey ? { [tab.paramKey]: rowId } : {}
      const { data } = await api.get(tab.endpoint, { params })
      tabData.value[tab.label] = data.items || []
    } catch { tabData.value[tab.label] = [] }
  }
}
async function loadStages(orderId: string) {
  try {
    const { data } = await api.get(`${props.config.apiPath}/${orderId}`)
    stages.value = data.stages || []
  } catch { stages.value = [] }
}
async function advanceStage(stage: any, status: '进行中' | '已完成') {
  try {
    await api.patch(`${props.config.apiPath}/delivery-stages/${stage.id}`, {
      status, actual_date: new Date().toISOString().slice(0, 10),
    })
    msg.success(status === '已完成' ? `阶段「${stage.stage}」已完成` : `阶段「${stage.stage}」已开始`)
    if (detailRow.value) await loadStages(detailRow.value.id)
  } catch (e: any) { msg.error(errMsg(e)) }
}
async function submit() {
  // 必填前端校验（缺必填给中文提示）
  const missing = props.config.fields
    .filter((f) => f.required && (form[f.key] === null || form[f.key] === undefined || form[f.key] === ''))
    .map((f) => f.label)
  if (missing.length) { msg.warning(`请填写必填项：${missing.join('、')}`); return }
  try {
    if (editing.value) await R.updateRes(props.config.apiPath, editing.value.id, { ...form })
    else await R.createRes(props.config.apiPath, { ...form })
    showModal.value = false; msg.success('已保存'); await refresh()
  } catch (e: any) {
    msg.error(errMsg(e))
  }
}
async function del(row: any) {
  try { await R.deleteRes(props.config.apiPath, row.id); msg.success('已删除'); await refresh() }
  catch (e: any) { msg.error(errMsg(e)) }
}

// 二期 W3-4：合同「核算判定信息」实时预览（纯函数预览端点，不落库；300ms 防抖）
const judgePreview = ref<{ method: string | null; rule: string; basis: string } | null>(null)
let previewTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => [form.project_id, form.type, form.pricing_authority, form.inventory_risk_bearer, form.principal_role],
  () => {
    if (!props.config.revenueJudge) return
    judgePreview.value = null
    if (!form.project_id || !form.type) return
    if (previewTimer) clearTimeout(previewTimer)
    previewTimer = setTimeout(async () => {
      try {
        const { data } = await api.get('/contracts/judge-preview', {
          params: {
            project_id: form.project_id, type: form.type,
            pricing_authority: form.pricing_authority || undefined,
            inventory_risk_bearer: form.inventory_risk_bearer || undefined,
            principal_role: form.principal_role || undefined,
          },
        })
        judgePreview.value = data
      } catch { judgePreview.value = null }
    }, 300)
  },
)

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
  act.fields?.forEach(f => { actionForm[f.key] = f.type === 'select' ? null : '' })
  if (act.fields?.length) { showActionModal.value = true } else { submitAction() }
}
async function submitAction() {
  if (!activeAction.value || !detailRow.value) return
  const act = activeAction.value
  // 必填校验（如人工覆盖核算路径的「原因」）
  const missing = (act.fields || [])
    .filter((f: any) => f.required && (actionForm[f.key] === null || actionForm[f.key] === undefined || actionForm[f.key] === ''))
    .map((f: any) => f.label)
  if (missing.length) { msg.warning(`请填写必填项：${missing.join('、')}`); return }
  try {
    const url = `${act.endpoint}/${detailRow.value.id}${act.action}`
    // 剥空串/null：可选数值字段（如变更的新金额）空串会被后端 Decimal 校验 422
    const body = Object.fromEntries(Object.entries({ ...actionForm }).filter(([, v]) => v !== '' && v !== null && v !== undefined))
    if (act.method === 'PATCH') await api.patch(url, body)
    else await api.post(url, body)
    msg.success(act.successMsg || '操作成功')
    showActionModal.value = false
    await refresh()
    const updated = items.value.find((i: any) => i.id === detailRow.value?.id)
    if (updated) detailRow.value = updated
    if (detailRow.value) await loadTabs(detailRow.value.id)  // 操作落库 → 重拉聚合 tabs（变更记录等）
  } catch (e: any) {
    msg.error(errMsg(e))
  }
}

// Excel 导入/导出
function onImportFinish({ event }: any) {
  try {
    const r = JSON.parse(event?.target?.response || '{}')
    if (r && r.imported != null) { msg.success(`导入成功: ${r.imported} 条`); refresh() }
    else if (r && r.detail) msg.error(errMsg({ response: { data: r } }))
    else msg.error('导入失败：文件格式不符')
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

// F4：实时生成 PDF（不落库，浏览器直接下载）。blob 下载范式同 exportData，endpoint 为 {apiPath}/{id}/pdf。
async function downloadPdf(row: any) {
  try {
    const resp = await api.get(`${props.config.apiPath}/${row.id}/pdf`, { responseType: 'blob' })
    const url = URL.createObjectURL(resp.data as unknown as Blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${props.config.title}-${String(row.id).slice(0, 8)}.pdf`; a.click()
    URL.revokeObjectURL(url)
    msg.success('PDF 已生成')
  } catch (e: any) { msg.error(errMsg(e)) }
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
      ...(props.config.workspaceLink ? [
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => router.push(`/projects/${row.id}/workspace`), title: '工作台' },
          { icon: () => h(NIcon, null, { default: () => h(Workflow, { size: 14 }) }) }),
      ] : []),
      ...(props.config.pdfExport ? [
        h(NTooltip, null, {
          trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => downloadPdf(row), title: '导出PDF' },
            { icon: () => h(NIcon, null, { default: () => h(FileText, { size: 14 }) }) }),
          default: () => '导出 PDF：实时生成合同正本，可直接打印或归档',
        }),
      ] : []),
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => openDetail(row), title: '详情' },
        { icon: () => h(NIcon, null, { default: () => h(Eye, { size: 14 }) }) }),
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => openEdit(row), title: '编辑' },
        { icon: () => h(NIcon, null, { default: () => h(Pencil, { size: 14 }) }) }),
      h(NPopconfirm, { onPositiveClick: () => del(row) }, {
        trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error', title: '删除' },
          { icon: () => h(NIcon, null, { default: () => h(Trash2, { size: 14 }) }) }),
        default: () => '删除后不可撤销，关联的业务数据可能受影响，确认删除？',
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
        <template #empty><n-empty :description="config.creatable !== false ? '暂无数据，点击右上角「新增」创建第一条' : '暂无数据'" style="padding:32px 0" /></template>
      </n-data-table>
    </div>

    <!-- 新增/编辑 -->
    <n-modal v-model:show="showModal" preset="card" :title="editing ? '编辑' : '新增'" style="width:520px;max-width:94vw">
      <n-form label-placement="left" :label-width="140">
        <template v-for="f in config.fields" :key="f.key">
          <n-divider v-if="f.section" style="margin:6px 0 14px;font-size:13px">{{ f.section }}</n-divider>
        <n-form-item :required="f.required" :show-feedback="false">
          <template #label>
            {{ f.label }}
            <n-tooltip v-if="f.hint" trigger="hover">
              <template #trigger>
                <n-icon style="margin-left:4px;cursor:help;vertical-align:middle;color:#94A3B8"><HelpCircle :size="14" /></n-icon>
              </template>
              {{ f.hint }}
            </n-tooltip>
          </template>
          <div style="width:100%">
            <n-select v-if="f.remoteOptions" v-model:value="form[f.key]" :options="remoteOpts[f.key] || []" filterable placeholder="请选择" />
            <n-select v-else-if="f.type === 'select'" v-model:value="form[f.key]" :options="f.options" clearable />
            <n-input-number v-else-if="f.type === 'number'" v-model:value="form[f.key]" :status="fieldWarn(f) ? 'warning' : undefined" style="width:100%" />
            <n-date-picker v-else-if="f.type === 'date'" type="date" style="width:100%"
              :value="ymdToTs(form[f.key])" @update:value="(ts: number | null) => form[f.key] = tsToYmd(ts)" />
            <n-input v-else v-model:value="form[f.key]" />
            <div v-if="fieldWarn(f)" class="tiny" style="color:#D97706;margin-top:2px">⚠ {{ fieldWarn(f) }}</div>
          </div>
        </n-form-item>
        </template>
      </n-form>
      <!-- 二期 W3-4：核算判定实时预览（纯函数预览，保存后才落库） -->
      <n-alert v-if="config.revenueJudge && judgePreview" :type="judgePreview.method ? 'info' : 'warning'"
        :bordered="false" style="margin-top:4px" data-testid="judge-preview">
        <template v-if="judgePreview.method">
          判定预览：<b>{{ judgePreview.method }}</b>（{{ judgePreview.rule }}）<br />
          <span class="tiny">{{ judgePreview.basis }}</span>
        </template>
        <template v-else>{{ judgePreview.basis }}</template>
      </n-alert>
      <n-alert v-else-if="config.revenueJudge && form.type === 'PURCHASE'" type="default" :bordered="false" style="margin-top:4px" data-testid="judge-preview">
        采购合同属成本侧，不参与收入核算路径判定
      </n-alert>
      <template #footer><n-space justify="end"><n-button @click="showModal = false">取消</n-button><n-button type="primary" @click="submit">保存</n-button></n-space></template>
    </n-modal>

    <!-- 详情抽屉 -->
    <n-drawer v-model:show="showDetail" :width="520" placement="right">
      <n-drawer-content :title="config.title + ' 详情'" closable>
        <WorkflowProgress v-if="detailRow?.project_id" :project-id="detailRow.project_id" style="margin-bottom:16px" />
        <n-descriptions v-if="detailRow" label-placement="left" bordered :column="1" size="small">
          <n-descriptions-item v-for="f in allFields" :key="f.key" :label="f.label">
            <span v-if="numKeys.has(f.key)" class="num">{{ money(detailRow[f.key]) }}</span>
            <n-tag v-else-if="tagKeys.has(f.key)" size="small" :type="statusTagType(detailRow[f.key]) as any" :bordered="false">{{ detailRow[f.key] ?? '-' }}</n-tag>
            <span v-else>{{ detailRow[f.key] ?? '-' }}</span>
          </n-descriptions-item>
        </n-descriptions>

        <!-- 二期 W3-4：核算判定信息（判定依据 + 确认留痕） -->
        <div v-if="config.revenueJudge && detailRow?.revenue_method" style="margin-top:20px" data-testid="judge-detail">
          <div class="muted" style="margin-bottom:8px;font-weight:600">核算判定信息</div>
          <n-alert type="info" :bordered="false">
            <div>核算路径：<b>{{ detailRow.revenue_method }}</b>
              <n-tag v-if="detailRow.method_confirmed_at" size="tiny" type="success" :bordered="false" style="margin-left:6px">已人工确认</n-tag>
            </div>
            <div class="tiny" style="margin-top:4px">{{ detailRow.method_judge_basis }}</div>
            <div v-if="detailRow.method_confirmed_at" class="tiny muted" style="margin-top:4px">
              确认时间：{{ String(detailRow.method_confirmed_at).slice(0, 19).replace('T', ' ') }}
            </div>
          </n-alert>
        </div>

        <!-- 文件上传 -->
        <div v-if="config.fileUpload && detailRow" style="margin-top:20px">
          <div class="muted" style="margin-bottom:8px;font-weight:600">附件管理</div>
          <div v-if="detailRow.file_path" style="margin-bottom:8px">
            <n-tag size="small" type="success" :bordered="false">{{ String(detailRow.file_path).slice(0, 30) }}</n-tag>
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
            <template v-for="act in visibleActions" :key="act.label">
              <n-tooltip v-if="act.tooltip">
                <template #trigger>
                  <n-button type="primary" @click="triggerAction(act)">{{ act.label }}</n-button>
                </template>
                {{ act.tooltip }}
              </n-tooltip>
              <n-button v-else type="primary" @click="triggerAction(act)">{{ act.label }}</n-button>
            </template>
          </n-space>
        </div>

        <!-- 交付阶段推进 -->
        <div v-if="config.stageFlow && stages.length" style="margin-top:20px">
          <div class="muted" style="margin-bottom:8px;font-weight:600">交付阶段</div>
          <div v-for="st in stages" :key="st.id" class="stage-row">
            <span class="stage-seq">{{ st.seq }}</span>
            <span class="stage-name">{{ st.stage }}</span>
            <n-tag size="tiny" :bordered="false"
              :type="st.status === '已完成' ? 'success' : st.status === '进行中' ? 'info' : 'default'">{{ st.status }}</n-tag>
            <span class="muted tiny">{{ st.actual_date || st.planned_date || '' }}</span>
            <n-button v-if="st.status === '未开始'" size="tiny" quaternary type="info" @click="advanceStage(st, '进行中')">开始</n-button>
            <n-button v-if="st.status !== '已完成'" size="tiny" quaternary type="success" @click="advanceStage(st, '已完成')">完成</n-button>
          </div>
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
        <n-form-item v-for="f in activeAction?.fields || []" :key="f.key" :label="f.label" :required="(f as any).required">
          <n-date-picker v-if="f.type === 'date'" type="date" style="width:100%"
            :value="ymdToTs(actionForm[f.key])" @update:value="(ts: number | null) => actionForm[f.key] = tsToYmd(ts)" />
          <n-select v-else-if="f.type === 'select'" v-model:value="actionForm[f.key]" :options="(f as any).options" style="width:100%" />
          <n-input v-else v-model:value="actionForm[f.key]" />
        </n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showActionModal = false">取消</n-button><n-button type="primary" @click="submitAction">确认</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<style scoped>
.crud-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.stage-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px dashed var(--c-border, #e5e7eb); }
.stage-row:last-child { border-bottom: none; }
.stage-seq { width: 18px; height: 18px; border-radius: 50%; background: var(--c-primary, #2563EB); color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center; flex: none; }
.stage-name { flex: 1; font-size: 13px; }
.table-wrap { padding: 4px; overflow: hidden; }
:deep(.n-data-table .n-data-table-th) { font-weight: 600; }
:deep(.num) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
