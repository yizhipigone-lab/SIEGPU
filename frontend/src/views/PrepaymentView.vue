<script setup lang="ts">
// 二期 W9-10：预付款台账（D2 裁定：聚合 devices 行为单一真源，不建 prepayments 表）。
// 行 = 有预付款的设备：总额 / 累计已结转 / 余额 / 结清标记。结转随按台计费自动发生（直线法）。
import { h, onMounted, ref } from 'vue'
import { NCard, NDataTable, NTag, useMessage } from 'naive-ui'
import { api } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money } from '../utils/format'

const msg = useMessage()
const items = ref<any[]>([])
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    const { data } = await api.get('/prepayments/summary')
    items.value = data.items
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}
onMounted(refresh)
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3>预付款台账</h3>
      <span class="muted tiny">按设备聚合（单一真源）；结转随每月按台计费自动发生</span>
    </div>
    <n-card size="small">
      <n-data-table size="small" :bordered="false" striped :loading="loading" :pagination="{ pageSize: 15 }"
        :columns="[
          { title: '设备SN', key: 'sn' },
          { title: '项目', key: 'project_name' },
          { title: '预付款总额', key: 'prepayment_amount', align: 'right' as const, render: (r: any) => money(r.prepayment_amount) },
          { title: '累计已结转', key: 'settled_amount', align: 'right' as const, render: (r: any) => money(r.settled_amount) },
          { title: '余额', key: 'remaining', align: 'right' as const, render: (r: any) => money(r.remaining) },
          { title: '状态', key: 'settled', width: 100, render: (r: any) =>
              h(NTag, { size: 'small', type: r.settled ? 'success' : 'warning', bordered: false },
                () => (r.settled ? '已结清' : '结转中')) },
        ]"
        :data="items"
        :row-key="(r: any) => r.device_id">
        <template #empty>暂无预付款记录（设备的 prepayment_amount &gt; 0 才会出现在这里）</template>
      </n-data-table>
    </n-card>
    <div class="muted tiny" style="margin-top:8px">
      口径：余额 = 预付款总额 − 累计已结转；售后回租出售时整笔结清（一期语义）；月结转 = 总额 ÷ 合同月数（直线法，尾差末月收敛）。
    </div>
  </div>
</template>

<style scoped>
.muted { color: #94A3B8; }
.tiny { font-size: 12px; }
</style>
