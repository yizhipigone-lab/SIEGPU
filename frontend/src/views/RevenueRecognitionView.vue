<script setup lang="ts">
// 三期 §4.2：收入确认管理。计费自动出草稿 → 审批中心通过（/payments 页）→ 已确认+Mock 凭证 → 已同步EBS。
// 本页：确认单列表（凭证详情）+ 科目映射配置 + 存量补草稿。
import { h, onMounted, reactive, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NForm, NFormItem, NInput, NModal, NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money } from '../utils/format'

const msg = useMessage()
const items = ref<any[]>([])
const mappings = ref<any[]>([])

async function refresh() {
  try {
    const [r, m] = await Promise.all([
      api.get('/revenue-recognitions'), api.get('/gl-account-mappings'),
    ])
    items.value = r.data.items
    mappings.value = m.data.items
  } catch (e: any) { msg.error(errMsg(e)) }
}
onMounted(refresh)

async function backfill() {
  try {
    const { data } = await api.post('/revenue-recognitions/generate', {})
    msg.success(`补草稿完成：新建 ${data.created} 张（已存在自动跳过）`)
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 新增科目映射 ----
const showMap = ref(false)
const mapForm = reactive({ business_event: '收入确认', revenue_method: null as string | null, debit_account: '', credit_account: '', description_template: '' })
async function submitMap() {
  if (!mapForm.debit_account || !mapForm.credit_account) { msg.warning('请填写借贷科目'); return }
  try {
    await api.post('/gl-account-mappings', { ...mapForm, description_template: mapForm.description_template || null })
    showMap.value = false; msg.success('映射已保存')
    Object.assign(mapForm, { business_event: '收入确认', revenue_method: null, debit_account: '', credit_account: '', description_template: '' })
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// S7（缺陷#7）：本页行内审批（草稿 → 通过/驳回），不再只能去付款管控页
async function approveRow(row: any) {
  if (!row.approval_id) { msg.warning('该草稿无关联审批单'); return }
  try {
    await api.post(`/approvals/${row.approval_id}/approve`)
    msg.success('已通过（状态→已确认，凭证+同步EBS）')
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}
const rejectTarget = ref<any | null>(null)
const rejectReason = ref('')
async function doRejectRow() {
  if (!rejectTarget.value || !rejectReason.value.trim()) { msg.warning('驳回必须填原因'); return }
  try {
    await api.post(`/approvals/${rejectTarget.value.approval_id}/reject`, { reason: rejectReason.value })
    msg.success('已驳回')
    rejectTarget.value = null; rejectReason.value = ''
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// 凭证展开
const voucherOf = ref<any | null>(null)
const statusType = (s: string) => ({ 草稿: 'warning', 已确认: 'info', 已同步EBS: 'success' }[s] || 'default')
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3>收入确认</h3>
      <n-space>
        <n-button size="small" quaternary @click="showMap = true">科目映射</n-button>
        <n-button size="small" quaternary @click="backfill">存量补草稿</n-button>
      </n-space>
    </div>

    <n-card title="收入确认单（开票成功即自动生成草稿；审批通过后出凭证并同步 EBS）" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 10 }"
        :columns="[
          { title: '项目', key: 'project_name', width: 140, render: (r: any) => r.project_name || '—' },
          { title: '期间', key: 'period_label', width: 90 },
          { title: '确认日', key: 'recognition_date', width: 110 },
          { title: '金额(不含税)', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
          { title: '核算路径', key: 'revenue_method', width: 100, render: (r: any) => r.revenue_method || '—' },
          { title: '状态', key: 'status', width: 110 },
          { title: '凭证', key: '__v', width: 90 },
          { title: '审批', key: '__a', width: 150, render: (r: any) =>
              r.status === '草稿' && r.approval_id
                ? h(NSpace, { size: 2 }, () => [
                    h(NButton, { size: 'tiny', type: 'success', quaternary: true, onClick: () => approveRow(r) }, () => '通过'),
                    h(NButton, { size: 'tiny', type: 'error', quaternary: true, onClick: () => rejectTarget = r }, () => '驳回'),
                  ])
                : null },
        ]"
        :data="items"
        :row-props="(row: any) => ({ style: 'cursor:pointer', onClick: () => row.voucher_json && (voucherOf = row) })">
        <template #empty>暂无确认单。销售发票开票成功即自动生成草稿；历史计费点右上角「存量补草稿」。</template>
      </n-data-table>
      <n-space style="margin-top:8px" wrap>
        <n-tag v-for="r in items.filter((x: any) => x.status !== '草稿')" :key="r.id" size="small"
          :type="statusType(r.status) as any" :bordered="false" style="cursor:pointer"
          @click="r.voucher_json && (voucherOf = r)">
          {{ r.period_label }} {{ r.status }}{{ r.voucher_json ? ' · 看凭证' : '' }}
        </n-tag>
      </n-space>
      <div class="muted tiny" style="margin-top:8px">草稿也可在「付款管控 → 审批中心」按类型筛选后通过/驳回（通用审批）。点凭证列可查看 Mock 凭证借贷科目。</div>
    </n-card>

    <n-card title="科目映射（业务事件 + 核算路径 → EBS 借贷科目；核算路径空=通用兜底）" size="small">
      <n-data-table size="small" :bordered="false" striped
        :columns="[
          { title: '业务事件', key: 'business_event', width: 110 },
          { title: '核算路径', key: 'revenue_method', width: 100, render: (r: any) => r.revenue_method || '通用' },
          { title: '借方科目', key: 'debit_account', width: 120 },
          { title: '贷方科目', key: 'credit_account', width: 120 },
          { title: '摘要模板', key: 'description_template', render: (r: any) => r.description_template || '—' },
        ]"
        :data="mappings">
        <template #empty>暂无映射。未配映射的确认单出凭证时会标注 mapping_missing。</template>
      </n-data-table>
    </n-card>

    <!-- 凭证详情 -->
    <n-modal :show="voucherOf !== null" preset="card" title="Mock 凭证" style="width:420px" @update:show="(v: boolean) => !v && (voucherOf = null)">
      <template v-if="voucherOf?.voucher_json">
        <div class="kv"><span>借方科目</span><b>{{ voucherOf.voucher_json.debit_account || '（缺映射）' }}</b></div>
        <div class="kv"><span>贷方科目</span><b>{{ voucherOf.voucher_json.credit_account || '（缺映射）' }}</b></div>
        <div class="kv"><span>金额(不含税)</span><b>{{ money(voucherOf.voucher_json.amount) }}</b></div>
        <div class="kv"><span>摘要</span><b>{{ voucherOf.voucher_json.description }}</b></div>
        <div v-if="voucherOf.voucher_json.mapping_missing" class="tiny" style="color:#D97706;margin-top:8px">⚠ 未配科目映射，请在下方「科目映射」补充</div>
      </template>
    </n-modal>

    <!-- 新增映射 -->
    <n-modal v-model:show="showMap" preset="card" title="新增科目映射" style="width:440px">
      <n-form label-placement="left" :label-width="100">
        <n-form-item label="业务事件"><n-input v-model:value="mapForm.business_event" /></n-form-item>
        <n-form-item label="核算路径">
          <n-select v-model:value="mapForm.revenue_method" clearable placeholder="空=通用兜底"
            :options="['总额法', '净额法', '经营租赁', '服务费', '待判定'].map((v) => ({ label: v, value: v }))" />
        </n-form-item>
        <n-form-item label="借方科目" required><n-input v-model:value="mapForm.debit_account" placeholder="如 1122.01 应收账款" /></n-form-item>
        <n-form-item label="贷方科目" required><n-input v-model:value="mapForm.credit_account" placeholder="如 6001.01 主营业务收入" /></n-form-item>
        <n-form-item label="摘要模板"><n-input v-model:value="mapForm.description_template" placeholder="支持 {period} 占位，如：确认{period}经营租赁收入" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showMap = false">取消</n-button><n-button type="primary" @click="submitMap">保存</n-button></n-space></template>
    </n-modal>
    <!-- 驳回原因（S7 行内审批） -->
    <n-modal :show="rejectTarget !== null" preset="card" title="驳回收入确认草稿" style="width:380px"
      @update:show="(v: boolean) => !v && (rejectTarget = null)">
      <n-form-item label="驳回原因" required>
        <n-input v-model:value="rejectReason" type="textarea" :rows="2" placeholder="必填" />
      </n-form-item>
      <template #footer><n-space justify="end"><n-button @click="rejectTarget = null">取消</n-button><n-button type="error" @click="doRejectRow">确认驳回</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<style scoped>
.muted { color: #94A3B8; }
.tiny { font-size: 12px; }
.kv { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px dashed #f0f0f0; font-size: 13px; }
.kv span { color: #94A3B8; }
</style>
