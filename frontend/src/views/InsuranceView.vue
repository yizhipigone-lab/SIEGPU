<script setup lang="ts">
// 二期 W7-8：保险管理（设备粒度）。保单列表 + 新增（按设备价值占比自动分摊）+ 详情抽屉
// （分摊明细 / 确认 / 归集进原值〔点亮前窗口〕/ 摊销预览 / 理赔登记）+ 投保配置。
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NDatePicker, NDrawer, NDrawerContent, NForm, NFormItem, NInput,
  NInputNumber, NModal, NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money, tsToYmd, ymdToTs } from '../utils/format'

const msg = useMessage()
const policies = ref<any[]>([])
const configs = ref<any[]>([])
const projects = ref<any[]>([])
const suppliers = ref<any[]>([])

async function refresh() {
  try {
    const [p, c] = await Promise.all([api.get('/insurance/policies'), api.get('/insurance/configs')])
    policies.value = p.data.items
    configs.value = c.data.items
  } catch (e: any) { msg.error(errMsg(e)) }
}
onMounted(async () => {
  refresh()
  try {
    const [pj, sp] = await Promise.all([api.get('/projects'), api.get('/suppliers')])
    projects.value = (pj.data.items || pj.data || []).map((x: any) => ({ label: x.name, value: x.id }))
    suppliers.value = (sp.data.items || sp.data || []).map((x: any) => ({ label: x.name, value: x.id }))
  } catch { /* 下拉备选为空不阻断 */ }
})

// ---- 新增保单 ----
const showCreate = ref(false)
const createForm = reactive({
  project_id: null as string | null, policy_type: '运输险', device_ids: [] as string[],
  policy_no: '', insurer_id: null as string | null, insured_amount: null as number | null,
  premium_rate: null as number | null, start_date: '', end_date: '',
  cost_allocation: null as string | null, amortization_months: null as number | null,
})
const deviceOpts = ref<{ label: string; value: string }[]>([])
async function onProjectPick(pid: string | null) {
  createForm.device_ids = []
  deviceOpts.value = []
  if (!pid) return
  try {
    const { data } = await api.get('/devices', { params: { project_id: pid } })
    deviceOpts.value = (data.items || []).map((d: any) => ({
      label: `${d.sn}（原值 ${money(d.purchase_value)}）`, value: d.id,
    }))
  } catch { deviceOpts.value = [] }
}
const premiumPreview = computed(() =>
  createForm.insured_amount != null && createForm.premium_rate != null
    ? (createForm.insured_amount * createForm.premium_rate).toFixed(2) : null)
async function submitCreate() {
  if (!createForm.project_id || !createForm.device_ids.length) {
    msg.warning('请选择项目并至少勾选一台设备'); return
  }
  try {
    await api.post('/insurance/policies', {
      ...createForm,
      policy_no: createForm.policy_no || null,
      start_date: createForm.start_date || null,
      end_date: createForm.end_date || null,
      amortization_months: createForm.amortization_months || null,
    })
    showCreate.value = false; msg.success('保单已创建（待确认），保费已按设备价值占比分摊')
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 新增配置 ----
const showCfg = ref(false)
const cfgForm = reactive({ policy_type: '运输险', default_rate: null as number | null, insured_ratio: 1, cost_allocation: null as string | null })
async function submitCfg() {
  try {
    await api.post('/insurance/configs', { ...cfgForm })
    showCfg.value = false; msg.success('配置已保存（对应险种将自动投保）')
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 详情抽屉 ----
const showDetail = ref(false)
const detail = ref<any | null>(null)
async function openDetail(row: any) {
  try {
    const { data } = await api.get(`/insurance/policies/${row.id}`)
    detail.value = data
    showDetail.value = true
  } catch (e: any) { msg.error(errMsg(e)) }
}
async function doConfirm() {
  try {
    await api.post(`/insurance/policies/${detail.value.id}/confirm`)
    msg.success('保单已确认生效'); await openDetail(detail.value); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}
async function doCollect() {
  try {
    await api.post(`/insurance/policies/${detail.value.id}/collect`)
    msg.success('保费已按分摊额归集进资产原值'); await openDetail(detail.value); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}
// 摊销预览
const amort = ref<any[] | null>(null)
async function showAmort() {
  try {
    const { data } = await api.get(`/insurance/policies/${detail.value.id}/amortization`)
    amort.value = data
  } catch (e: any) { amort.value = null; msg.error(errMsg(e)) }
}
// 理赔登记
const showClaim = ref(false)
const claimForm = reactive({ claim_date: '', amount: null as number | null, description: '' })
async function submitClaim() {
  if (!claimForm.claim_date || !claimForm.amount) { msg.warning('请填写理赔日期和金额'); return }
  try {
    await api.post(`/insurance/policies/${detail.value.id}/claims`, { ...claimForm, description: claimForm.description || null })
    showClaim.value = false; msg.success('理赔已登记')
    await openDetail(detail.value); await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

const statusType = (s: string) => ({ 已生效: 'success', 待确认: 'warning', 理赔中: 'error', 已到期: 'default', 已退保: 'default' }[s] || 'default')
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3>保险管理</h3>
      <n-space>
        <n-button size="small" quaternary @click="showCfg = true">投保配置</n-button>
        <n-button type="primary" size="small" @click="showCreate = true">新增保单</n-button>
      </n-space>
    </div>

    <n-card title="保单" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 10 }"
        :columns="[
          { title: '险种', key: 'policy_type', width: 90 },
          { title: '保单号', key: 'policy_no', render: (r: any) => r.policy_no || '—' },
          { title: '保额', key: 'insured_amount', align: 'right' as const, render: (r: any) => money(r.insured_amount) },
          { title: '保费', key: 'premium_amount', align: 'right' as const, render: (r: any) => money(r.premium_amount) },
          { title: '状态', key: 'status', width: 100 },
          { title: '触发', key: 'trigger_event', width: 80, render: (r: any) => r.trigger_event || '—' },
          { title: '到期日', key: 'end_date', width: 110, render: (r: any) => r.end_date || '—' },
        ]"
        :data="policies"
        :row-props="(row: any) => ({ style: 'cursor:pointer', onClick: () => openDetail(row) })">
        <template #empty>暂无保单。点「新增保单」手工录入，或配好「投保配置」后设备进在途/点亮将自动生成待确认保单。</template>
      </n-data-table>
    </n-card>

    <n-card title="投保配置（险种默认费率/投保比例；配置后设备进在途/点亮自动投保）" size="small">
      <n-data-table size="small" :bordered="false" striped
        :columns="[
          { title: '险种', key: 'policy_type', width: 100 },
          { title: '默认费率', key: 'default_rate', render: (r: any) => r.default_rate ?? '—' },
          { title: '投保比例', key: 'insured_ratio', render: (r: any) => r.insured_ratio ?? '—' },
          { title: '归集口径', key: 'cost_allocation', render: (r: any) => r.cost_allocation || '—' },
          { title: '启用', key: 'active', width: 70, render: (r: any) => (r.active ? '✅' : '—') },
        ]"
        :data="configs">
        <template #empty>暂无配置。未配置险种不会自动投保（不影响设备推进）。</template>
      </n-data-table>
    </n-card>

    <!-- 新增保单 -->
    <n-modal v-model:show="showCreate" preset="card" title="新增保单" style="width:560px;max-width:94vw">
      <n-form label-placement="left" :label-width="110">
        <n-form-item label="项目" required>
          <n-select v-model:value="createForm.project_id" :options="projects" filterable placeholder="选择项目"
            @update:value="onProjectPick" />
        </n-form-item>
        <n-form-item label="险种" required>
          <n-select v-model:value="createForm.policy_type" :options="['运输险', '财产险'].map((v) => ({ label: v, value: v }))" />
        </n-form-item>
        <n-form-item label="覆盖设备" required>
          <n-select v-model:value="createForm.device_ids" :options="deviceOpts" multiple filterable
            placeholder="先选项目；保费按设备原值占比自动分摊" data-testid="policy-devices" />
        </n-form-item>
        <n-form-item label="保单号"><n-input v-model:value="createForm.policy_no" /></n-form-item>
        <n-form-item label="保险公司"><n-select v-model:value="createForm.insurer_id" :options="suppliers" filterable clearable placeholder="可选" /></n-form-item>
        <n-form-item label="保额(元)"><n-input-number v-model:value="createForm.insured_amount" :min="0" style="width:100%" /></n-form-item>
        <n-form-item label="费率(小数)">
          <div style="width:100%">
            <n-input-number v-model:value="createForm.premium_rate" :min="0" :precision="8" style="width:100%" placeholder="如 0.001" />
            <div v-if="premiumPreview" class="tiny" style="color:#2563EB;margin-top:2px">保费预览：{{ premiumPreview }} 元（保存后按设备价值占比分摊）</div>
          </div>
        </n-form-item>
        <n-form-item label="起保日期">
          <n-date-picker type="date" style="width:100%" :value="ymdToTs(createForm.start_date)" @update:value="(ts: number | null) => createForm.start_date = tsToYmd(ts)" />
        </n-form-item>
        <n-form-item label="到期日期">
          <n-date-picker type="date" style="width:100%" :value="ymdToTs(createForm.end_date)" @update:value="(ts: number | null) => createForm.end_date = tsToYmd(ts)" />
        </n-form-item>
        <n-form-item label="归集口径">
          <n-select v-model:value="createForm.cost_allocation" clearable placeholder="资产原值（点亮前）/ 长期待摊"
            :options="['资产原值', '长期待摊'].map((v) => ({ label: v, value: v }))" />
        </n-form-item>
        <n-form-item v-if="createForm.cost_allocation === '长期待摊'" label="摊销月数">
          <n-input-number v-model:value="createForm.amortization_months" :min="1" style="width:100%" />
        </n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showCreate = false">取消</n-button><n-button type="primary" @click="submitCreate">保存</n-button></n-space></template>
    </n-modal>

    <!-- 投保配置 -->
    <n-modal v-model:show="showCfg" preset="card" title="新增投保配置" style="width:420px">
      <n-form label-placement="left" :label-width="100">
        <n-form-item label="险种"><n-select v-model:value="cfgForm.policy_type" :options="['运输险', '财产险'].map((v) => ({ label: v, value: v }))" /></n-form-item>
        <n-form-item label="默认费率"><n-input-number v-model:value="cfgForm.default_rate" :min="0" :precision="8" style="width:100%" placeholder="如 0.001" /></n-form-item>
        <n-form-item label="投保比例"><n-input-number v-model:value="cfgForm.insured_ratio" :min="0" :precision="4" style="width:100%" placeholder="1 = 全额投保" /></n-form-item>
        <n-form-item label="归集口径"><n-select v-model:value="cfgForm.cost_allocation" clearable :options="['资产原值', '长期待摊'].map((v) => ({ label: v, value: v }))" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showCfg = false">取消</n-button><n-button type="primary" @click="submitCfg">保存</n-button></n-space></template>
    </n-modal>

    <!-- 详情抽屉 -->
    <n-drawer v-model:show="showDetail" :width="520" placement="right">
      <n-drawer-content v-if="detail" :title="`保单详情（${detail.policy_type}）`" closable>
        <n-space align="center" style="margin-bottom:12px">
          <n-tag :type="statusType(detail.status) as any" :bordered="false">{{ detail.status }}</n-tag>
          <span v-if="detail.collected_at" class="tiny muted">已归集进原值</span>
        </n-space>
        <div class="kv"><span>保单号</span><b>{{ detail.policy_no || '—' }}</b></div>
        <div class="kv"><span>保额</span><b>{{ money(detail.insured_amount) }}</b></div>
        <div class="kv"><span>保费</span><b>{{ money(detail.premium_amount) }}</b></div>
        <div class="kv"><span>归集口径</span><b>{{ detail.cost_allocation || '—' }}</b></div>
        <div class="kv"><span>起止</span><b>{{ detail.start_date || '—' }} ~ {{ detail.end_date || '—' }}</b></div>

        <div class="muted" style="margin:14px 0 8px;font-weight:600">设备分摊（按原值占比）</div>
        <n-data-table size="small" :bordered="false" striped
          :columns="[
            { title: '设备SN', key: 'sn' },
            { title: '分摊保费', key: 'allocated_amount', align: 'right' as const, render: (r: any) => money(r.allocated_amount) },
          ]"
          :data="detail.devices || []" />

        <div style="margin-top:16px" class="muted">业务操作</div>
        <n-space style="margin-top:8px" wrap>
          <n-button v-if="detail.status === '待确认'" type="primary" size="small" @click="doConfirm">确认生效</n-button>
          <n-button v-if="detail.cost_allocation === '资产原值' && !detail.collected_at" size="small" @click="doCollect">归集进原值</n-button>
          <n-button v-if="detail.cost_allocation === '长期待摊'" size="small" @click="showAmort">摊销预览</n-button>
          <n-button v-if="!['已到期', '已退保'].includes(detail.status)" size="small" @click="showClaim = true">理赔登记</n-button>
        </n-space>

        <div v-if="amort" style="margin-top:12px" data-testid="amort-preview">
          <div class="muted tiny" style="margin-bottom:6px">摊销计划（{{ amort.length }} 期，末月吃尾差）</div>
          <n-data-table size="small" :bordered="false" striped :max-height="220"
            :columns="[
              { title: '期次', key: 'period', width: 70 },
              { title: '摊销额', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
            ]"
            :data="amort" />
        </div>

        <div v-if="detail.claims?.length" style="margin-top:12px">
          <div class="muted tiny" style="margin-bottom:6px">理赔记录</div>
          <div v-for="(c, i) in detail.claims" :key="i" class="tiny" style="padding:4px 0;border-bottom:1px dashed #eee">
            {{ c.date }} · {{ money(c.amount) }} · {{ c.description || '—' }}
          </div>
        </div>
      </n-drawer-content>
    </n-drawer>

    <!-- 理赔登记 -->
    <n-modal v-model:show="showClaim" preset="card" title="理赔登记" style="width:380px">
      <n-form label-placement="left" :label-width="90">
        <n-form-item label="理赔日期">
          <n-date-picker type="date" style="width:100%" :value="ymdToTs(claimForm.claim_date)" @update:value="(ts: number | null) => claimForm.claim_date = tsToYmd(ts)" />
        </n-form-item>
        <n-form-item label="金额(元)"><n-input-number v-model:value="claimForm.amount" :min="0" style="width:100%" /></n-form-item>
        <n-form-item label="说明"><n-input v-model:value="claimForm.description" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showClaim = false">取消</n-button><n-button type="primary" @click="submitClaim">保存</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<style scoped>
.muted { color: #94A3B8; }
.tiny { font-size: 12px; }
.kv { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px dashed #f0f0f0; font-size: 13px; }
.kv span { color: #94A3B8; }
</style>
