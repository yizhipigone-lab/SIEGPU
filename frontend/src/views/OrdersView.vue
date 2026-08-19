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
// 步骤导航实体级跳转：订单步骤目标是采购订单列表。
// ?detail=<id> 由下方 GenericCrud 的 pending-detail 机制打开采购订单详情抽屉（Task 6），
// ?project_id=<pid> 由 GenericCrud 作为列表过滤消费（GET /orders?project_id=，后端支持）。
// 带这两个参数时强制落在采购订单页签（即使带 ?tab=sales 也以实体跳转意图为准）。
const tab = ref<string>(
  route.query.tab === 'sales' && !route.query.detail && !route.query.project_id ? 'sales' : 'purchase',
)

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
