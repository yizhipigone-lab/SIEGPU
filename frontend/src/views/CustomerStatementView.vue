<script setup lang="ts">
// 客户对账单（F3）—— 按客户聚合三流（合同额 → 计费 → 开票 → 回款）。
// 后端口径全不含税（report_service._customer_contract_totals），让 gap 可直接相减。
// 数据源：GET /reports/customer-statement/summary（客户下拉）+ /reports/customer-statement（明细）。
import { h, onMounted, ref, watch } from 'vue'
import {
  NCard, NDataTable, NGi, NGrid, NSelect, NStatistic, NTag, useMessage,
} from 'naive-ui'
import { api } from '../api/client'
import { money } from '../utils/format'
import { errMsg } from '../utils/errMsg'
import EmptyState from '../components/EmptyState.vue'

const msg = useMessage()

// 客户列表（summary，按未回款额倒序）+ 当前对账单
const customers = ref<any[]>([])
const selectedId = ref<string | null>(null)
const stmt = ref<any | null>(null)

async function loadCustomers() {
  try {
    const { data } = await api.get('/reports/customer-statement/summary')
    customers.value = data.items || []
    // 默认选未回款最大的第一个（summary 已按 gap_uncollected 倒序）
    if (customers.value.length && !selectedId.value) {
      selectedId.value = customers.value[0].customer_id
    }
  } catch (e: any) { msg.error(errMsg(e)) }
}

async function loadStatement() {
  if (!selectedId.value) { stmt.value = null; return }
  try {
    const { data } = await api.get('/reports/customer-statement', { params: { customer_id: selectedId.value } })
    stmt.value = data
  } catch (e: any) { msg.error(errMsg(e)); stmt.value = null }
}

const customerOpts = () => customers.value.map((c: any) => ({
  // label 带未回款额，方便财务一眼定位最该跟的客户
  label: `${c.customer_name}（${c.contract_count} 份合同，未回款 ${money(c.gap_uncollected)}）`,
  value: c.customer_id,
}))

watch(selectedId, loadStatement)
onMounted(async () => { await loadCustomers(); await loadStatement() })

const contractCols = [
  { title: '合同号', key: 'contract_no', width: 160, render: (r: any) => r.contract_no || '—' },
  { title: '合同额(不含税)', key: 'contract_amount', align: 'right' as const, render: (r: any) => money(r.contract_amount) },
  { title: '已计费', key: 'billed', align: 'right' as const, render: (r: any) => money(r.billed) },
  { title: '已开票', key: 'invoiced', align: 'right' as const, render: (r: any) => money(r.invoiced) },
  { title: '已回款', key: 'received', align: 'right' as const, render: (r: any) => money(r.received) },
  { title: '未计费', key: 'gap', align: 'right' as const, render: (r: any) => {
      const v = Number(r.gap || 0); return Math.abs(v) < 0.005 ? '—' : h('span', { style: 'color:#EA580C;font-weight:600' }, money(v))
    } },
  { title: '状态', key: 'status', width: 90, render: (r: any) =>
      h(NTag, { size: 'small', bordered: false }, () => r.status || '—') },
]

const lineCols = [
  { title: '日期', key: 'date', width: 110, render: (r: any) => r.date || '—' },
  { title: '合同号', key: 'contract_no', width: 160, render: (r: any) => r.contract_no || '—' },
  { title: '类型', key: 'type', width: 80, render: (r: any) =>
      h(NTag, { size: 'small', bordered: false,
        type: r.type === '回款' ? 'success' : r.type === '开票' ? 'info' : 'warning' }, () => r.type) },
  { title: '金额(不含税)', key: 'amount_ex_tax', align: 'right' as const, render: (r: any) => money(r.amount_ex_tax) },
  { title: '状态', key: 'status', width: 90, render: (r: any) => r.status || '—' },
]
</script>

<template>
  <div>
    <div class="cs-header">
      <h3>客户对账单</h3>
      <n-select
        v-model:value="selectedId"
        :options="customerOpts()"
        placeholder="选择客户查看对账单"
        filterable
        class="cs-picker"
      />
    </div>

    <EmptyState v-if="!customers.length"
      description="还没有客户对账数据，销售合同确立并产生计费/开票/回款后，这里会自动汇总" />

    <template v-else-if="stmt">
      <!-- 四 KPI：合同额 / 已计费 / 已开票 / 已回款（+ 未开票/未回款差额） -->
      <n-grid :cols="4" :x-gap="12" :y-gap="12" responsive="screen" item-responsive
        style="margin-bottom:16px">
        <n-gi span="4 m:1">
          <n-card size="small">
            <n-statistic label="合同额(不含税)" :value="money(stmt.contract_amount)" />
          </n-card>
        </n-gi>
        <n-gi span="4 m:1">
          <n-card size="small">
            <n-statistic label="已计费" :value="money(stmt.billed)" />
          </n-card>
        </n-gi>
        <n-gi span="4 m:1">
          <n-card size="small">
            <n-statistic label="已开票" :value="money(stmt.invoiced)" />
          </n-card>
        </n-gi>
        <n-gi span="4 m:1">
          <n-card size="small">
            <n-statistic label="已回款" :value="money(stmt.received)">
              <template #suffix>
                <div class="cs-gap">
                  未计费 <b>{{ money(stmt.gap_unbilled) }}</b> · 未回款 <b>{{ money(stmt.gap_uncollected) }}</b>
                </div>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
      </n-grid>

      <!-- 按合同 -->
      <n-card title="按合同" size="small" style="margin-bottom:16px">
        <div class="muted tiny" style="margin-bottom:8px">
          该客户全部销售合同的三流对账：合同额 → 计费 → 开票 → 回款。红冲已自动剔除。
        </div>
        <n-data-table :columns="contractCols" :data="stmt.contracts" :bordered="false" size="small" striped />
      </n-card>

      <!-- 流水明细 -->
      <n-card title="流水明细" size="small">
        <div class="muted tiny" style="margin-bottom:8px">
          计费单 + 发票（开票/回款）按日期倒序合并；同一笔业务从计费到回款一目了然。
        </div>
        <n-data-table :columns="lineCols" :data="stmt.line_items" :bordered="false" size="small" striped>
          <template #empty>
            <EmptyState description="暂无计费/开票/回款记录" />
          </template>
        </n-data-table>
      </n-card>
    </template>
  </div>
</template>

<style scoped>
.cs-header {
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.cs-picker { width: 460px; max-width: 100%; }
.cs-gap {
  font-size: 12px;
  color: #64748B;
  margin-top: 4px;
}
.cs-gap b { color: #EA580C; font-weight: 600; }
:deep(.n-statistic .n-statistic-value) {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
</style>
