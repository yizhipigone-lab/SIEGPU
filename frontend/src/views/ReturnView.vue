<script setup lang="ts">
// 三期 §4.4：采购退货管理。链路：退货申请 → 出库确认 → 供应商收货 → 红字发票 → 退款核销。
// 列表 + 新增（项目→设备多选，金额=Σ原值，预付款追回额自动算）+ 详情抽屉（设备明细 + 逐步推进按钮）。
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NDrawer, NDrawerContent, NForm, NFormItem, NInput, NModal,
  NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money } from '../utils/format'

const msg = useMessage()
const items = ref<any[]>([])
const projects = ref<any[]>([])

const NEXT_LABEL: Record<string, string> = {
  退货申请: '出库确认', 已出库: '供应商收货', 供应商已收货: '开红字发票', 已开红字发票: '退款核销',
}

async function refresh() {
  try {
    const { data } = await api.get('/returns')
    items.value = data.items
  } catch (e: any) { msg.error(errMsg(e)) }
}
onMounted(async () => {
  refresh()
  try {
    const pj = await api.get('/projects')
    projects.value = (pj.data.items || []).map((x: any) => ({ label: x.name, value: x.id }))
  } catch { /* 备选为空不阻断 */ }
})

// ---- 新增退货 ----
const showCreate = ref(false)
const createForm = reactive({ project_id: null as string | null, return_type: '到货不合格', device_ids: [] as string[], reason: '' })
const deviceOpts = ref<{ label: string; value: string }[]>([])
async function onProjectPick(pid: string | null) {
  createForm.device_ids = []
  deviceOpts.value = []
  if (!pid) return
  try {
    const { data } = await api.get('/devices', { params: { project_id: pid } })
    deviceOpts.value = (data.items || [])
      .filter((d: any) => !['点亮验收', '已退货'].includes(d.status))
      .map((d: any) => ({ label: `${d.sn}（${d.status} · 原值 ${money(d.purchase_value)}）`, value: d.id }))
  } catch { deviceOpts.value = [] }
}
async function submitCreate() {
  if (!createForm.project_id || !createForm.device_ids.length) { msg.warning('请选择项目并至少勾选一台设备'); return }
  try {
    await api.post('/returns', { ...createForm, reason: createForm.reason || null })
    showCreate.value = false; msg.success('退货申请已创建')
    Object.assign(createForm, { project_id: null, return_type: '到货不合格', device_ids: [], reason: '' })
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 详情 + 推进 ----
const showDetail = ref(false)
const detail = ref<any | null>(null)
async function openDetail(row: any) {
  try {
    const { data } = await api.get(`/returns/${row.id}`)
    detail.value = data
    showDetail.value = true
  } catch (e: any) { msg.error(errMsg(e)) }
}
async function doAdvance() {
  try {
    await api.post(`/returns/${detail.value.id}/advance`, {})
    msg.success(`已推进：${NEXT_LABEL[detail.value.status]} 完成`)
    await openDetail(detail.value)
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

const statusType = (s: string) => ({ 退货申请: 'warning', 已出库: 'info', 供应商已收货: 'info', 已开红字发票: 'info', 已退款核销: 'success', 预付款已冲回: 'success' }[s] || 'default')
const nextLabel = computed(() => (detail.value ? NEXT_LABEL[detail.value.status] : null))
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3>退货管理</h3>
      <n-button type="primary" size="small" @click="showCreate = true">新增退货</n-button>
    </div>

    <n-card title="退货单" size="small">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 10 }"
        :columns="[
          { title: '类型', key: 'return_type', width: 110 },
          { title: '状态', key: 'status', width: 120 },
          { title: '退货金额', key: 'total_amount', align: 'right' as const, render: (r: any) => money(r.total_amount) },
          { title: '预付款追回', key: 'prepayment_recover', align: 'right' as const, render: (r: any) => money(r.prepayment_recover) },
          { title: '原因', key: 'reason', render: (r: any) => r.reason || '—' },
        ]"
        :data="items"
        :row-props="(row: any) => ({ style: 'cursor:pointer', onClick: () => openDetail(row) })">
        <template #empty>暂无退货单。点亮验收的设备不可退（先红冲计费/处置资产）。</template>
      </n-data-table>
    </n-card>

    <!-- 新增退货 -->
    <n-modal v-model:show="showCreate" preset="card" title="新增退货" style="width:520px;max-width:94vw">
      <n-form label-placement="left" :label-width="100">
        <n-form-item label="项目" required>
          <n-select v-model:value="createForm.project_id" :options="projects" filterable placeholder="选择项目" @update:value="onProjectPick" />
        </n-form-item>
        <n-form-item label="退货类型" required>
          <n-select v-model:value="createForm.return_type" :options="['到货不合格', '压测不通过', '合同终止'].map((v) => ({ label: v, value: v }))" />
        </n-form-item>
        <n-form-item label="退货设备" required>
          <n-select v-model:value="createForm.device_ids" :options="deviceOpts" multiple filterable
            placeholder="先选项目；点亮验收/已退货不出现在候选" data-testid="return-devices" />
        </n-form-item>
        <n-form-item label="原因"><n-input v-model:value="createForm.reason" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showCreate = false">取消</n-button><n-button type="primary" @click="submitCreate">保存</n-button></n-space></template>
    </n-modal>

    <!-- 详情抽屉 -->
    <n-drawer v-model:show="showDetail" :width="520" placement="right">
      <n-drawer-content v-if="detail" :title="`退货单详情（${detail.return_type}）`" closable>
        <n-space align="center" style="margin-bottom:12px">
          <n-tag :type="statusType(detail.status) as any" :bordered="false">{{ detail.status }}</n-tag>
        </n-space>
        <div class="kv"><span>退货金额</span><b>{{ money(detail.total_amount) }}</b></div>
        <div class="kv"><span>预付款追回</span><b>{{ money(detail.prepayment_recover) }}</b></div>
        <div class="kv"><span>红字发票</span><b>{{ detail.red_invoice_id ? '已开' : '—' }}</b></div>
        <div class="kv"><span>退款流水</span><b>{{ detail.refund_txn_id ? '已登记' : '—' }}</b></div>
        <div class="kv"><span>原因</span><b>{{ detail.reason || '—' }}</b></div>

        <div class="muted" style="margin:14px 0 8px;font-weight:600">退货设备</div>
        <n-data-table size="small" :bordered="false" striped
          :columns="[
            { title: '设备SN', key: 'sn' },
            { title: '退货额', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
          ]"
          :data="detail.devices || []" />

        <div v-if="nextLabel" style="margin-top:16px">
          <n-button type="primary" @click="doAdvance" data-testid="return-advance">{{ nextLabel }}</n-button>
          <div class="muted tiny" style="margin-top:6px">
            链路：退货申请 → 出库确认（设备置已退货）→ 供应商收货（已转固资产减少）→ 开红字发票 → 退款核销
          </div>
        </div>
        <div v-else class="muted tiny" style="margin-top:16px">已到终态（退款核销/预付款冲回）。</div>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<style scoped>
.muted { color: #94A3B8; }
.tiny { font-size: 12px; }
.kv { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px dashed #f0f0f0; font-size: 13px; }
.kv span { color: #94A3B8; }
</style>
