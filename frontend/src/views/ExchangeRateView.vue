<script setup lang="ts">
// 二期 W5-6：币种与汇率管理。三区块：币种主数据（本币唯一）/ 汇率表（取值=最近不未来）/ 汇兑损益科目规则。
// 量纲铁律：rate 全精度 DECIMAL(18,8) 存取不 round；金额两位，仅「外币×率→人民币」q2（D6 对照表）。
import { onMounted, reactive, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NDatePicker, NForm, NFormItem, NInput, NInputNumber, NModal,
  NSpace, NSwitch, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { tsToYmd, ymdToTs } from '../utils/format'

const msg = useMessage()
const currencies = ref<any[]>([])
const rates = ref<any[]>([])
const glRules = ref<any[]>([])

async function refresh() {
  try {
    const [c, r, g] = await Promise.all([
      api.get('/currencies'), api.get('/exchange-rates'), api.get('/exchange-gain-loss-rules'),
    ])
    currencies.value = c.data.items
    rates.value = r.data.items
    glRules.value = g.data.items
  } catch (e: any) { msg.error(errMsg(e)) }
}
onMounted(refresh)

// ---- 币种新增 ----
const showCur = ref(false)
const curForm = reactive({ code: '', name: '', symbol: '', is_base: false })
async function submitCurrency() {
  if (!curForm.code || !curForm.name) { msg.warning('请填写币种代码和名称'); return }
  try {
    await api.post('/currencies', { ...curForm, symbol: curForm.symbol || null })
    showCur.value = false; msg.success('已新增币种')
    Object.assign(curForm, { code: '', name: '', symbol: '', is_base: false })
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}
async function setBase(row: any) {
  try {
    await api.patch(`/currencies/${row.id}`, { is_base: true })
    msg.success(`已把 ${row.code} 设为本币（其他币种自动退位）`)
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}

// ---- 汇率新增 + 试算 ----
const showRate = ref(false)
const rateForm = reactive({ from_currency: '', to_currency: 'CNY', rate: null as number | null, effective_date: '' as string, source: '' })
async function submitRate() {
  if (!rateForm.from_currency || !rateForm.to_currency || !rateForm.rate || !rateForm.effective_date) {
    msg.warning('请填写币种对、汇率和生效日期'); return
  }
  try {
    await api.post('/exchange-rates', { ...rateForm, source: rateForm.source || null })
    showRate.value = false; msg.success('已录入汇率')
    Object.assign(rateForm, { from_currency: '', to_currency: 'CNY', rate: null, effective_date: '', source: '' })
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}
// 试算：取值规则=最近不未来（后端 get_rate）
const trial = reactive({ from_currency: 'USD', to_currency: 'CNY', on_date: '' as string })
const trialResult = ref<string | null>(null)
async function runTrial() {
  if (!trial.on_date) { msg.warning('请选择业务日期'); return }
  try {
    const { data } = await api.get('/exchange-rates/lookup', {
      params: { from_currency: trial.from_currency, to_currency: trial.to_currency, on_date: trial.on_date },
    })
    trialResult.value = `1 ${data.from_currency} = ${data.rate} ${data.to_currency}（${data.rate_type}，取值日 ≤ ${data.on_date} 的最近一条）`
  } catch (e: any) { trialResult.value = null; msg.error(errMsg(e)) }
}

// ---- 科目规则新增 ----
const showGl = ref(false)
const glForm = reactive({ scenario: '', gl_account_code: '', description: '' })
async function submitGl() {
  if (!glForm.scenario || !glForm.gl_account_code) { msg.warning('请填写场景和科目码'); return }
  try {
    await api.post('/exchange-gain-loss-rules', { ...glForm, description: glForm.description || null })
    showGl.value = false; msg.success('已新增规则')
    Object.assign(glForm, { scenario: '', gl_account_code: '', description: '' })
    await refresh()
  } catch (e: any) { msg.error(errMsg(e)) }
}
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3>币种与汇率</h3>
      <n-space>
        <n-button size="small" quaternary @click="showCur = true">新增币种</n-button>
        <n-button size="small" quaternary @click="showRate = true">录入汇率</n-button>
        <n-button size="small" quaternary @click="showGl = true">新增科目规则</n-button>
      </n-space>
    </div>

    <n-card title="币种主数据" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped
        :columns="[
          { title: '代码', key: 'code', width: 90 },
          { title: '名称', key: 'name' },
          { title: '符号', key: 'symbol', width: 70 },
          { title: '本币', key: 'is_base' },
        ]"
        :data="currencies">
        <template #empty>暂无币种，点右上角「新增币种」（建议先建 CNY 并设为本币）</template>
      </n-data-table>
      <div class="muted tiny" style="margin-top:6px">
        本币 = 记账本位币（人民币）。设新本币后其他币种自动退位；未填币种的单据一律按人民币处理。
      </div>
      <div v-for="c in currencies" :key="c.id" style="display:none"></div>
      <n-space style="margin-top:8px">
        <n-tag v-for="c in currencies" :key="c.code" size="small"
          :type="c.is_base ? 'success' : 'default'" :bordered="false"
          style="cursor:pointer" @click="!c.is_base && setBase(c)">
          {{ c.code }} {{ c.name }}{{ c.is_base ? '（本币）' : ' · 点击设为本币' }}
        </n-tag>
      </n-space>
    </n-card>

    <n-card title="汇率表（直接标价法：1 外币 = N 元人民币）" size="small" style="margin-bottom:14px">
      <n-form inline label-placement="left" style="margin-bottom:10px">
        <n-form-item label="试算">
          <n-input v-model:value="trial.from_currency" style="width:80px" placeholder="USD" />
        </n-form-item>
        <n-form-item label="→">
          <n-input v-model:value="trial.to_currency" style="width:80px" placeholder="CNY" />
        </n-form-item>
        <n-form-item label="业务日期">
          <n-date-picker type="date" style="width:150px"
            :value="ymdToTs(trial.on_date)" @update:value="(ts: number | null) => trial.on_date = tsToYmd(ts)" />
        </n-form-item>
        <n-button size="small" type="primary" @click="runTrial">取值</n-button>
      </n-form>
      <div v-if="trialResult" data-testid="rate-trial-result" style="margin-bottom:10px">{{ trialResult }}</div>
      <n-data-table size="small" :bordered="false" striped
        :columns="[
          { title: '币种对', key: 'pair' },
          { title: '汇率', key: 'rate' },
          { title: '类型', key: 'rate_type', width: 90 },
          { title: '生效日期', key: 'effective_date', width: 110 },
          { title: '来源', key: 'source', width: 100 },
        ]"
        :data="rates.map((r: any) => ({ ...r, pair: `${r.from_currency} → ${r.to_currency}` }))"
        :pagination="{ pageSize: 10 }">
        <template #empty>暂无汇率，点右上角「录入汇率」</template>
      </n-data-table>
      <div class="muted tiny" style="margin-top:6px">取值规则：同币种恒为 1；否则取「生效日期 ≤ 业务日」的最近一条（最近不未来）。无记录报错，绝不静默按 1 折算。</div>
    </n-card>

    <n-card title="汇兑损益科目规则" size="small">
      <n-data-table size="small" :bordered="false" striped
        :columns="[
          { title: '场景', key: 'scenario', width: 140 },
          { title: 'EBS 科目码', key: 'gl_account_code', width: 160 },
          { title: '说明', key: 'description' },
        ]"
        :data="glRules">
        <template #empty>暂无规则（如：收款核销 → 汇兑损益科目码）</template>
      </n-data-table>
    </n-card>

    <!-- 新增币种 -->
    <n-modal v-model:show="showCur" preset="card" title="新增币种" style="width:380px">
      <n-form label-placement="left" :label-width="90">
        <n-form-item label="代码"><n-input v-model:value="curForm.code" placeholder="如 USD（自动大写）" /></n-form-item>
        <n-form-item label="名称"><n-input v-model:value="curForm.name" placeholder="如 美元" /></n-form-item>
        <n-form-item label="符号"><n-input v-model:value="curForm.symbol" placeholder="如 $" /></n-form-item>
        <n-form-item label="设为本币"><n-switch v-model:value="curForm.is_base" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showCur = false">取消</n-button><n-button type="primary" @click="submitCurrency">保存</n-button></n-space></template>
    </n-modal>

    <!-- 录入汇率 -->
    <n-modal v-model:show="showRate" preset="card" title="录入汇率" style="width:420px">
      <n-form label-placement="left" :label-width="100">
        <n-form-item label="外币"><n-input v-model:value="rateForm.from_currency" placeholder="如 USD" /></n-form-item>
        <n-form-item label="目标币"><n-input v-model:value="rateForm.to_currency" placeholder="CNY" /></n-form-item>
        <n-form-item label="汇率"><n-input-number v-model:value="rateForm.rate" :precision="8" :min="0" style="width:100%" placeholder="1 外币 = N 元目标币，如 7.12345678" /></n-form-item>
        <n-form-item label="生效日期">
          <n-date-picker type="date" style="width:100%"
            :value="ymdToTs(rateForm.effective_date)" @update:value="(ts: number | null) => rateForm.effective_date = tsToYmd(ts)" />
        </n-form-item>
        <n-form-item label="来源"><n-input v-model:value="rateForm.source" placeholder="央行/中行/手工" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showRate = false">取消</n-button><n-button type="primary" @click="submitRate">保存</n-button></n-space></template>
    </n-modal>

    <!-- 新增科目规则 -->
    <n-modal v-model:show="showGl" preset="card" title="新增汇兑损益科目规则" style="width:420px">
      <n-form label-placement="left" :label-width="100">
        <n-form-item label="场景"><n-input v-model:value="glForm.scenario" placeholder="如 收款核销 / 付款核销 / 期末重估" /></n-form-item>
        <n-form-item label="EBS 科目码"><n-input v-model:value="glForm.gl_account_code" placeholder="如 6603.01" /></n-form-item>
        <n-form-item label="说明"><n-input v-model:value="glForm.description" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showGl = false">取消</n-button><n-button type="primary" @click="submitGl">保存</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<style scoped>
.muted { color: #94A3B8; }
.tiny { font-size: 12px; }
</style>
