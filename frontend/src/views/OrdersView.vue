<script setup lang="ts">
// 订单中心：采购订单 / 销售订单 单页 + 顶部 Tab（与合同、验收同一交互模式）。
// 采购订单 = orders 实体（GenericCrud 配置驱动）；销售订单 = sales_orders 实体（独立视图组件）。
// Tab 状态写入 ?tab=purchase|sales，供工作台/命令面板/角色导航深链直达对应页签。
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NTabPane, NTabs } from 'naive-ui'
import GenericCrud from '../components/GenericCrud.vue'
import { MODULES } from '../config/modules'
import SalesOrdersView from './SalesOrdersView.vue'

const route = useRoute()
const router = useRouter()
const tab = ref<string>(route.query.tab === 'sales' ? 'sales' : 'purchase')

watch(tab, (t) => {
  router.replace({ query: { ...route.query, tab: t } })
})
</script>

<template>
  <div>
    <n-tabs v-model:value="tab" type="line" size="medium" style="margin-bottom:12px" data-testid="order-tabs">
      <n-tab-pane name="purchase" tab="采购订单" />
      <n-tab-pane name="sales" tab="销售订单" />
    </n-tabs>
    <GenericCrud v-if="tab === 'purchase'" :config="MODULES.orders" />
    <SalesOrdersView v-else embedded />
  </div>
</template>
