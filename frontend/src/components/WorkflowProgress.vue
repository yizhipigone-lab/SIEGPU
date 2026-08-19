<script setup lang="ts">
/**
 * 流程进度条：详情抽屉顶部展示项目 11 步流程当前进展，步骤可点击跳转对应实体。
 * 数据源与 ProjectWorkspace 同源：GET /workflows/{project_id} → { steps(含实体 id), current_step, status }。
 * 仅在实体带 project_id 时由 GenericCrud 挂载（无项目归属的主数据不显示）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NSpin, NStep, NSteps } from 'naive-ui'
import { api } from '../api/client'
import { roleName } from '../utils/role'

const props = defineProps<{ projectId: string }>()
const router = useRouter()
const wf = ref<any>(null)
const loading = ref(false)

async function load() {
  if (!props.projectId) return
  loading.value = true
  try {
    const { data } = await api.get(`/workflows/${props.projectId}`)
    wf.value = data
  } catch { wf.value = null }
  finally { loading.value = false }
}
onMounted(load)
watch(() => props.projectId, load)

const steps = computed<any[]> (() => wf.value?.steps || [])
const currentStep = computed(() => steps.value.find((s: any) => s.seq === wf.value?.current_step))

function stepStatus(s: any): 'process' | 'finish' | 'wait' | 'error' {
  if (s.status === 'done') return 'finish'
  if (s.seq === wf.value?.current_step) return 'process'
  return 'wait' // pending / skip 统一显示为未完成
}

// 步骤→跳转目标：单实体直达详情（query.detail 打开详情抽屉），多实体跳过滤列表，无实体不可跳。
function stepTarget(s: any): string | null {
  const pid = props.projectId
  const name = s.name
  if (name === '项目建立') return `/master/projects?detail=${pid}`
  if (name === '销售合同')
    return s.sales_contract_count === 1
      ? `/master/contracts?detail=${s.sales_contract_id}`
      : (s.sales_contract_count ? `/master/contracts?project_id=${pid}&type=SALES` : null)
  if (name === '采购合同')
    return s.purchase_contract_count === 1
      ? `/master/contracts?detail=${s.purchase_contract_id}`
      : (s.purchase_contract_count ? `/master/contracts?project_id=${pid}&type=PURCHASE` : null)
  if (name === '批次订单' || name === '采购订单')
    return s.order_count === 1
      ? `/orders?detail=${s.order_id}`
      : (s.order_count ? `/orders?project_id=${pid}` : null)
  if (name === '设备导入' || name === '设备到货' || name === '设备上架') return `/devices?project_id=${pid}`
  return null
}

function goStep(s: any) {
  const t = stepTarget(s)
  if (t) router.push(t)
}
</script>

<template>
  <div class="wf-progress">
    <n-spin v-if="loading" size="small" />
    <template v-else-if="wf">
      <n-steps size="small">
        <n-step
          v-for="s in steps" :key="s.seq"
          :status="stepStatus(s)"
          :title="`Step ${s.seq}`"
          :description="s.name"
          :class="{ 'wf-step-clickable': !!stepTarget(s) }"
          @click="goStep(s)"
        />
      </n-steps>
      <div v-if="currentStep" class="wf-tip">
        当前进行：<strong>Step {{ currentStep.seq }} {{ currentStep.name }}</strong>
        <span v-if="currentStep.doer_role"> · 待 {{ roleName(currentStep.doer_role) }} 处理</span>
      </div>
      <div v-else-if="wf.status === 'done'" class="wf-tip">流程已全部完成</div>
    </template>
    <div v-else class="muted tiny">无流程信息</div>
  </div>
</template>

<style scoped>
.wf-progress { padding: 2px 0 6px; }
.wf-tip { margin-top: 10px; font-size: 12px; color: #64748B; }
.wf-step-clickable { cursor: pointer; }
.wf-step-clickable:hover :deep(.n-step-content__title) { color: var(--c-primary, #2563EB); text-decoration: underline; }
</style>
