<script setup lang="ts">
// 三期 §4.3：对账中心（1 维 → 7 维）。七张卡：销售全链路 / 采购四单 / 资产交付 / 监管账户 /
// 汇兑损益 / 业财一致性(Mock 注入演示) / 三流差异明细（按客户/供应商筛选）。差异 flags 标红。
import { onMounted, ref } from 'vue'
import { NButton, NCard, NDataTable, NSelect, NTag, useMessage } from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money } from '../utils/format'

const msg = useMessage()
const d1 = ref<any[]>([])
const d2 = ref<any[]>([])
const d3 = ref<any[]>([])
const d4 = ref<any[]>([])
const d5 = ref<any[]>([])
const d6 = ref<any[]>([])
const d7 = ref<any[]>([])
const injected = ref(false)
const customers = ref<any[]>([])
const suppliers = ref<any[]>([])
const filterCustomer = ref<string | null>(null)
const filterSupplier = ref<string | null>(null)

function flagCell(flags: string[]) {
  return flags?.length ? flags.join('、') : '—'
}
async function loadDim6() {
  const { data } = await api.get('/reconciliation-center/ebs-consistency', { params: { inject_demo: injected.value } })
  d6.value = data.items
}
async function loadDim7() {
  const { data } = await api.get('/reconciliation-center/flow-diffs', {
    params: { customer_id: filterCustomer.value || undefined, supplier_id: filterSupplier.value || undefined },
  })
  d7.value = data.items
}
async function refresh() {
  try {
    const [a, b, c, d, e] = await Promise.all([
      api.get('/reconciliation-center/sales-chain'),
      api.get('/reconciliation-center/purchase-chain'),
      api.get('/reconciliation-center/asset-delivery'),
      api.get('/reconciliation-center/supervised-accounts'),
      api.get('/reconciliation-center/fx-check'),
    ])
    d1.value = a.data.items; d2.value = b.data.items; d3.value = c.data.items
    d4.value = d.data.items; d5.value = e.data.items
    await loadDim6(); await loadDim7()
  } catch (e: any) { msg.error(errMsg(e)) }
}
onMounted(async () => {
  refresh()
  try {
    const [c, s] = await Promise.all([api.get('/customers'), api.get('/suppliers')])
    customers.value = (c.data.items || []).map((x: any) => ({ label: x.name, value: x.id }))
    suppliers.value = (s.data.items || []).map((x: any) => ({ label: x.name, value: x.id }))
  } catch { /* 备选为空不阻断 */ }
})
async function toggleInject() {
  injected.value = !injected.value
  await loadDim6()
}

// 行级标红：有 flags 的行加红色类
const rowClass = (row: any) => (row.flags?.length ? 'diff-row' : '')
const flagCol = { title: '差异标记', key: 'flags', render: (r: any) => flagCell(r.flags) }
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3>对账中心</h3>
      <span class="muted tiny">7 维对账；有差异的行整行标红</span>
    </div>

    <n-card title="1. 销售全链路（合同额→计费→开票→收款→已确认收入）" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :row-class-name="rowClass"
        :columns="[
          { title: '合同号', key: 'contract_no', width: 110 },
          { title: '合同额', key: 'contract_amount', align: 'right' as const, render: (r: any) => money(r.contract_amount) },
          { title: '已计费', key: 'billed', align: 'right' as const, render: (r: any) => money(r.billed) },
          { title: '已开票', key: 'invoiced', align: 'right' as const, render: (r: any) => money(r.invoiced) },
          { title: '已收款', key: 'received', align: 'right' as const, render: (r: any) => money(r.received) },
          { title: '已确认收入', key: 'recognized', align: 'right' as const, render: (r: any) => money(r.recognized) },
          flagCol,
        ]" :data="d1">
        <template #empty>暂无销售合同</template>
      </n-data-table>
    </n-card>

    <n-card title="2. 采购四单（合同→发票→付款，含预付款核销核对）" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 8 }" :row-class-name="rowClass"
        :columns="[
          { title: '合同号', key: 'contract_no', width: 110 },
          { title: '合同额', key: 'contract_amount', align: 'right' as const, render: (r: any) => money(r.contract_amount) },
          { title: '已开票', key: 'invoiced', align: 'right' as const, render: (r: any) => money(r.invoiced) },
          { title: '已付款', key: 'paid', align: 'right' as const, render: (r: any) => money(r.paid) },
          { title: '预付款余额', key: 'prepayment_remaining', align: 'right' as const, render: (r: any) => money(r.prepayment_remaining) },
          flagCol,
        ]" :data="d2">
        <template #empty>暂无采购合同</template>
      </n-data-table>
    </n-card>

    <n-card title="3. 资产交付（采购→到货→转固→点亮，单台计数）" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 8 }" :row-class-name="rowClass"
        :columns="[
          { title: '项目', key: 'project_name' },
          { title: '采购', key: 'ordered', width: 70, align: 'right' as const },
          { title: '入库', key: 'devices', width: 70, align: 'right' as const },
          { title: '到货+', key: 'arrived', width: 70, align: 'right' as const },
          { title: '转固', key: 'capitalized', width: 70, align: 'right' as const },
          { title: '点亮', key: 'lit', width: 70, align: 'right' as const },
          flagCol,
        ]" :data="d3">
        <template #empty>暂无项目</template>
      </n-data-table>
    </n-card>

    <n-card title="4. 监管账户（租金收入 vs 还款支出 vs 最低留存）" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 8 }" :row-class-name="rowClass"
        :columns="[
          { title: '合同号', key: 'contract_no', width: 110 },
          { title: '租金已回款', key: 'received', align: 'right' as const, render: (r: any) => money(r.received) },
          { title: '还款支出', key: 'repaid', align: 'right' as const, render: (r: any) => money(r.repaid) },
          { title: '留存余额', key: 'balance', align: 'right' as const, render: (r: any) => money(r.balance) },
          { title: '最低留存', key: 'min_retention', align: 'right' as const, render: (r: any) => money(r.min_retention) },
          flagCol,
        ]" :data="d4">
        <template #empty>暂无监管户合同（合同「收款账户类型」=监管户才会出现）</template>
      </n-data-table>
    </n-card>

    <n-card title="5. 汇兑损益（入账 vs 设备分摊核对）" size="small" style="margin-bottom:14px">
      <n-data-table size="small" :bordered="false" striped :pagination="{ pageSize: 8 }" :row-class-name="rowClass"
        :columns="[
          { title: '日期', key: 'transaction_date', width: 110 },
          { title: '方向', key: 'direction', width: 60 },
          { title: '入账金额', key: 'amount', align: 'right' as const, render: (r: any) => money(r.amount) },
          { title: '已分摊至设备', key: 'split_to_devices', align: 'right' as const, render: (r: any) => money(r.split_to_devices) },
          { title: '摘要', key: 'note', ellipsis: { tooltip: true } },
          flagCol,
        ]" :data="d5">
        <template #empty>暂无汇兑损益记录</template>
      </n-data-table>
    </n-card>

    <n-card size="small" style="margin-bottom:14px">
      <template #header>
        6. 业财一致性（SIEGPU vs EBS，Mock）
        <n-button size="tiny" quaternary style="margin-left:8px" data-testid="toggle-inject" @click="toggleInject">
          {{ injected ? '关闭模拟差异' : '注入 3 条模拟差异' }}
        </n-button>
        <span v-if="injected" class="tiny" style="color:#D97706">（演示模式：应收+1000 / 资产−500 / 资金+233.33）</span>
      </template>
      <n-data-table size="small" :bordered="false" striped :row-class-name="rowClass"
        :columns="[
          { title: '项目', key: 'item', width: 110 },
          { title: 'SIEGPU', key: 'siegpu', align: 'right' as const, render: (r: any) => money(r.siegpu) },
          { title: 'EBS', key: 'ebs', align: 'right' as const, render: (r: any) => money(r.ebs) },
          { title: '差异', key: 'diff', align: 'right' as const, render: (r: any) => money(r.diff) },
          flagCol,
        ]" :data="d6" />
    </n-card>

    <n-card size="small">
      <template #header>7. 三流差异明细（只列有差异的行）</template>
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <n-select v-model:value="filterCustomer" :options="customers" filterable clearable placeholder="按客户筛选" style="width:220px" @update:value="loadDim7" />
        <n-select v-model:value="filterSupplier" :options="suppliers" filterable clearable placeholder="按供应商筛选" style="width:220px" @update:value="loadDim7" />
      </div>
      <n-data-table size="small" :bordered="false" striped :row-class-name="rowClass"
        :columns="[
          { title: '侧', key: 'side', width: 60 },
          { title: '对方', key: 'party_name' },
          { title: '合同号', key: 'contract_no', width: 110 },
          { title: '开票', key: 'invoiced', align: 'right' as const, render: (r: any) => money(r.invoiced) },
          flagCol,
        ]" :data="d7">
        <template #empty>无差异——全域三流一致 ✅</template>
      </n-data-table>
    </n-card>
  </div>
</template>

<style scoped>
.muted { color: #94A3B8; }
.tiny { font-size: 12px; }
:deep(.diff-row td) { background: #FEF2F2 !important; color: #B91C1C; }
</style>
