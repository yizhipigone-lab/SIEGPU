<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NCard, NTag, NSpace, NDivider,
  NEmpty, NSpin, NModal, NInput, NPopconfirm, useMessage,
} from 'naive-ui'
import { ArrowLeft, Check, SkipForward, RefreshCw, Play } from 'lucide-vue-next'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { roleName } from '../utils/role'
import { useAuthStore } from '../stores/auth'
import StepDrawer from '../components/StepDrawer.vue'

const route = useRoute()
const router = useRouter()
const msg = useMessage()
const auth = useAuthStore()
const wf = ref<any>(null)
const loading = ref(false)

// 与后端 workflows.py 对齐：标记完成需 FINANCE_DIRECTOR/ADMIN；必做步骤强制跳过同权限
const canManage = computed(() => auth.role === 'FINANCE_DIRECTOR' || auth.role === 'ADMIN')

const projectId = computed(() => route.params.id as string)

const steps = computed(() => wf.value?.steps || [])
const currentStep = computed(() => steps.value.find((s: any) => s.seq === wf.value?.current_step))
const doneSteps = computed(() => steps.value.filter((s: any) => s.status === 'done'))
const pendingSteps = computed(() => steps.value.filter((s: any) => s.status === 'pending' && s.seq !== wf.value?.current_step))

const progressPct = computed(() => {
  if (!steps.value.length) return 0
  const done = steps.value.filter((s: any) => s.status === 'done' || s.status === 'skip').length
  return Math.round((done / steps.value.length) * 100)
})

const statusColor: Record<string, string> = {
  done: '#B45309', pending: '#CBD5E1', skip: '#F59E0B', current: '#2563EB',
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/workflows/${projectId.value}`)
    wf.value = data
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}

async function doRefresh() {
  loading.value = true
  try {
    const { data } = await http.post(`/workflows/${projectId.value}/refresh`)
    wf.value = data
    msg.success('进度已刷新')
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}

// —— 跳过（NModal + 必填原因） ——
const showSkipModal = ref(false)
const skipSeq = ref<number | null>(null)
const skipReason = ref('')
const skipStepRequired = ref(true)
const skipSubmitting = ref(false)

function openSkip(s: any) {
  skipSeq.value = s.seq
  skipStepRequired.value = s.required !== false
  skipReason.value = ''
  showSkipModal.value = true
}

async function confirmSkip(): Promise<boolean> {
  const reason = skipReason.value.trim()
  if (!reason) { msg.warning('请填写跳过原因'); return false }
  if (skipSeq.value === null) return false
  skipSubmitting.value = true
  try {
    await http.post(`/workflows/${projectId.value}/skip/${skipSeq.value}`, { reason })
    msg.success(`步骤 ${skipSeq.value} 已跳过`)
    showSkipModal.value = false
    load()
    return true
  } catch (e: any) { msg.error(errMsg(e)); return false }
  finally { skipSubmitting.value = false }
}

// —— 手动标记完成（NPopconfirm + 可填审计备注） ——
const completeNote = ref('')
const completeSubmitting = ref(false)

async function doComplete(seq: number) {
  completeSubmitting.value = true
  try {
    const note = completeNote.value.trim() || undefined
    await http.post(`/workflows/${projectId.value}/steps/${seq}/complete`, { note })
    msg.success(`步骤 ${seq} 已标记完成`)
    completeNote.value = ''
    load()
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { completeSubmitting.value = false }
}

// 步骤状态文字 + 颜色（替代原 ✓/⊘/○ 纯符号）
function stepTag(s: any): { text: string; type: 'success' | 'warning' | 'info' | 'default' } {
  if (s.status === 'done') return { text: '已完成', type: 'success' }
  if (s.status === 'skip') return { text: '已跳过', type: 'warning' }
  if (s.seq === wf.value?.current_step) return { text: '进行中', type: 'info' }
  return { text: '待处理', type: 'default' }
}

const showDrawer = ref(false)
const drawerStep = ref<any | null>(null)

// 非抽屉步骤的 module → 路由显式映射（对照 router/index.ts 与 config/modules.ts）
const MODULE_ROUTE: Record<string, string> = {
  project: '/master/projects',
  contract: '/master/contracts',
  order: '/master/orders',
  delivery: '/master/orders',
  sales_order: '/sales-orders',
  capital: '/capital',
  leasing: '/leasing',
  acceptance: '/acceptances',
  confirmation: '/confirmations',
  billing: '/billing',
  invoice: '/invoices',
  profit: '/profit',
}

function handleStep(s: any) {
  if (s.status === 'done' || s.status === 'skip') return
  if (s.drawer) {
    drawerStep.value = s
    showDrawer.value = true
  } else if (s.module) {
    const path = MODULE_ROUTE[s.module] || `/master/${s.module}`
    router.push({ path, query: { project_id: projectId.value } })
  }
}

onMounted(load)
watch(() => route.params.id, load)
</script>

<template>
  <n-spin :show="loading">
    <div v-if="wf">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <n-button quaternary @click="router.back()">
          <template #icon><ArrowLeft :size="16" /></template>
          返回
        </n-button>
        <n-space>
          <n-button size="small" @click="doRefresh">
            <template #icon><RefreshCw :size="14" /></template>
            刷新进度
          </n-button>
        </n-space>
      </div>

      <!-- Progress bar -->
      <div style="background:#F1F5F9;border-radius:8px;padding:16px;margin-bottom:16px">
        <div style="font-size:20px;font-weight:700;margin-bottom:4px">
          {{ progressPct }}%
        </div>
        <div style="width:100%;height:6px;background:#E2E8F0;border-radius:3px;overflow:hidden">
          <div :style="{
            width: progressPct + '%', height: '100%',
            background: 'linear-gradient(90deg, #B45309, #F59E0B)',
            transition: 'width 0.5s',
          }" />
        </div>
        <div style="font-size:13px;color:#64748B;margin-top:6px">
          {{ doneSteps.length }} / {{ steps.length }} 步完成 · 状态：{{ wf.status }}
        </div>
      </div>

      <!-- Current step -->
      <n-card v-if="currentStep" size="small" style="margin-bottom:16px;border-left:4px solid #2563EB">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>
              <n-tag type="info" size="small" style="margin-right:8px">当前</n-tag>
              Step {{ currentStep.seq }} — {{ currentStep.name }}
            </span>
            <n-space>
              <n-popconfirm
                v-if="canManage"
                positive-text="确认标记" negative-text="取消"
                @positive-click="doComplete(currentStep.seq)"
              >
                <template #trigger>
                  <n-button size="tiny" :loading="completeSubmitting">标记完成</n-button>
                </template>
                <div style="max-width:260px">
                  <div style="margin-bottom:8px">手动标记完成将绕过自动检测，需财务总监权限。</div>
                  <n-input
                    v-model:value="completeNote" type="textarea" size="small"
                    placeholder="审计备注（选填）：为什么手动标记完成"
                    :autosize="{ minRows: 2, maxRows: 4 }"
                  />
                </div>
              </n-popconfirm>
              <n-button
                v-if="canManage || currentStep.required === false"
                size="tiny" quaternary type="warning" @click="openSkip(currentStep)"
              >
                跳过
              </n-button>
            </n-space>
          </div>
        </template>
        <div>
          <div style="color:#64748B;font-size:13px;margin-bottom:8px">
            负责人：{{ roleName(currentStep.doer_role) }}
            <template v-if="currentStep.approver_role">
              · 审批：{{ roleName(currentStep.approver_role) }}
            </template>
          </div>
          <n-button type="primary" size="small" @click="handleStep(currentStep)">
            <template #icon><Play :size="14" /></template>
            立即处理
          </n-button>
        </div>
      </n-card>

      <!-- Timeline -->
      <div style="max-height:500px;overflow-y:auto">
        <div v-for="s in steps" :key="s.seq" style="display:flex;align-items:flex-start;padding:8px 0;border-bottom:1px solid #F1F5F9">
          <div :style="{
            width: 10, height: 10, borderRadius: '50%',
            background: s.seq === wf.current_step ? '#2563EB' : s.status === 'done' ? '#B45309' : s.status === 'skip' ? '#F59E0B' : '#CBD5E1',
            marginTop: 5, marginRight: 12, flexShrink: 0,
          }" />
          <div style="flex:1">
            <div style="display:flex;justify-content:space-between">
              <span :style="{ fontWeight: s.seq === wf.current_step ? 700 : 400 }">
                {{ s.name }}
              </span>
              <n-tag :type="stepTag(s).type" size="tiny">
                {{ stepTag(s).text }}
              </n-tag>
            </div>
            <div style="font-size:12px;color:#94A3B8">
              {{ roleName(s.doer_role) }}
              <span v-if="s.completed_at"> · {{ s.completed_at?.slice(0, 10) }}</span>
              <span v-if="s.completed_by"> · 操作人：{{ s.completed_by }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <n-empty v-else description="项目暂无工作流" />

    <!-- 步骤抽屉 -->
    <step-drawer
      v-model:show="showDrawer" :project-id="projectId" :step="drawerStep" @done="load"
    />

    <!-- 跳过原因弹窗 -->
    <n-modal
      v-model:show="showSkipModal" preset="dialog" title="跳过步骤"
      positive-text="确认跳过" negative-text="取消"
      :positive-button-props="{ loading: skipSubmitting }"
      @positive-click="confirmSkip"
    >
      <div style="margin-bottom:8px">
        将跳过 Step {{ skipSeq }}。
        <span v-if="skipStepRequired" style="color:#D97706">该步骤为必做步骤，强制跳过需财务总监权限。</span>
      </div>
      <n-input
        v-model:value="skipReason" type="textarea" placeholder="跳过原因（必填）"
        :autosize="{ minRows: 2, maxRows: 4 }"
      />
    </n-modal>
  </n-spin>
</template>
