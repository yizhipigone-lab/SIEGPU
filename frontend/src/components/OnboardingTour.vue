<script setup lang="ts">
/**
 * 首次登录「分步引导 tour」（新手友好专项）—— 高亮气泡 + 步进进度 + 可跳过。
 *
 * - 非阻塞：遮罩/高亮框 pointer-events:none，不挡新手直接点目标；气泡按钮可点。
 * - 任意点击页面、路由跳转、或走完三步即自动关闭并写入 localStorage（siegpu:tourDone）。
 * - 目标缺失（如某角色无待办卡）时降级为居中气泡，不报错。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton } from 'naive-ui'

const STEPS: Array<{ sel: string; title: string; body: string }> = [
  { sel: '[data-testid="flow-map"]', title: '① 先看全局流程图', body: '整条链路分「采购→交付→财务」三段接力，高亮的是你负责的环节，点节点可直达对应页面。' },
  { sel: '[data-testid="command-palette-btn"]', title: '② 随时 Ctrl+K 直达', body: '想不起某个功能在哪？按 Ctrl+K（Mac ⌘K）输入动作词，如「放款 / 验收 / 开票」。' },
  { sel: '[data-testid="flow-map"]', title: '③ 跟待办走', body: '首页「待处理」卡会列出轮到你的步骤，点「立即处理」进工作台办理；办完会有「下一步」提示。' },
]

const emit = defineEmits<{ (e: 'finish'): void }>()
const router = useRouter()

const shown = ref(true)
const idx = ref(0)
const rect = ref<{ top: number; left: number; width: number; height: number } | null>(null)

function locate() {
  if (!shown.value) return
  const el = document.querySelector(STEPS[idx.value].sel) as HTMLElement | null
  rect.value = el ? el.getBoundingClientRect() : null
}

let unregisterRoute: (() => void) | null = null

function teardown() {
  window.removeEventListener('resize', locate)
  window.removeEventListener('scroll', locate, true)
  window.removeEventListener('pointerdown', onAnyPointer, true)
  if (unregisterRoute) {
    unregisterRoute()
    unregisterRoute = null
  }
}

function finish() {
  if (!shown.value) return
  shown.value = false
  try {
    localStorage.setItem('siegpu:tourDone', '1')
  } catch {
    /* ignore */
  }
  teardown()
  emit('finish')
}

function next() {
  if (idx.value < STEPS.length - 1) {
    idx.value++
    locate()
  } else {
    finish()
  }
}

function onAnyPointer(e: PointerEvent) {
  // 点气泡内（下一步/跳过）不关；点气泡外任意处视为已上手，收尾
  const t = e.target as HTMLElement | null
  if (t && typeof t.closest === 'function' && t.closest('.tour-bubble')) return
  finish()
}
function onRouteChange() {
  finish()
}

onMounted(() => {
  try {
    if (localStorage.getItem('siegpu:tourDone') === '1') {
      shown.value = false
      return
    }
  } catch {
    /* ignore */
  }
  locate()
  window.addEventListener('resize', locate)
  window.addEventListener('scroll', locate, true)
  window.addEventListener('pointerdown', onAnyPointer, true)
  unregisterRoute = router.afterEach(onRouteChange)
})

onBeforeUnmount(teardown)

const step = computed(() => STEPS[idx.value])

const bubbleStyle = computed(() => {
  if (!rect.value) {
    return { top: '42%', left: '50%', transform: 'translate(-50%, -50%)' }
  }
  const r = rect.value
  const bottom = r.top + r.height
  const top = bottom + 12 + 190 < window.innerHeight ? bottom + 12 : Math.max(12, r.top - 210)
  const left = Math.min(Math.max(12, r.left), Math.max(12, window.innerWidth - 340))
  return { top: `${top}px`, left: `${left}px` }
})
</script>

<template>
  <div v-if="shown" class="tour" @pointerdown.stop>
    <div class="tour-backdrop" />
    <div
      v-if="rect"
      class="tour-hl"
      :style="{ top: rect.top + 'px', left: rect.left + 'px', width: rect.width + 'px', height: rect.height + 'px' }"
    />
    <div class="tour-bubble" :style="bubbleStyle" data-testid="onboarding-tour">
      <div class="tour-step">{{ idx + 1 }} / {{ STEPS.length }} · 新手引导</div>
      <div class="tour-title">{{ step.title }}</div>
      <div class="tour-body">{{ step.body }}</div>
      <div class="tour-actions">
        <n-button size="tiny" quaternary @click="finish">跳过</n-button>
        <n-button size="tiny" type="primary" @click="next">
          {{ idx < STEPS.length - 1 ? '下一步' : '知道了' }}
        </n-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tour-backdrop {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.45);
  z-index: 2000;
  pointer-events: none;
}
.tour-hl {
  position: fixed;
  z-index: 2001;
  border: 2px solid #F59E0B;
  border-radius: 10px;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.25);
  pointer-events: none;
  transition: all 0.2s ease;
}
.tour-bubble {
  position: fixed;
  z-index: 2002;
  width: 320px;
  background: #FFFFFF;
  border-radius: 12px;
  padding: 14px 16px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.28);
  color: #1E293B;
}
.tour-step { font-size: 11px; color: #94A3B8; margin-bottom: 4px; }
.tour-title { font-size: 15px; font-weight: 700; color: #B45309; }
.tour-body { font-size: 13px; color: #475569; margin-top: 6px; line-height: 1.7; }
.tour-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
</style>
