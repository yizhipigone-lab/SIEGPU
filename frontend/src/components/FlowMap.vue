<script setup lang="ts">
/**
 * 可点击业务流程图（三泳道接力版）—— 首页「我在流程的哪一环」的主入口。
 *
 * 升级要点（新手友好专项）：
 *  - 11 步直线 → 采购/交付/财务三条泳道，首尾相接展示「谁做什么、在哪交接」；
 *  - 单据(doc=FileText) / 动作(action=Zap) 用图标+底色区分，消除「建单子 vs 推进度」混排；
 *  - 本角色泳道整条高亮；有待办的步骤打「进行中」脉冲点，点开即办。
 *
 * 数据源：roleGuide.ts FLOW_LANES / FLOW_STEPS（含 kind/aliases）。
 * 交互：点节点直达对应业务页面；当前角色无权访问的节点置灰并提示「由 XX 负责」。
 * 复用：Dashboard 流程图卡片 + 「看完整流程」弹窗共用本组件。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon, NTooltip } from 'naive-ui'
import { ChevronDown, ChevronRight, FileText, Lock, Zap } from 'lucide-vue-next'
import { FLOW_LANES } from '../utils/roleGuide'
import type { FlowStep } from '../utils/roleGuide'
import { isMenuAllowed, readShowAllMenus } from '../utils/roleMenu'
import { roleName } from '../utils/role'
import { useAuthStore } from '../stores/auth'

const props = withDefaults(defineProps<{
  /** 当前角色负责的步骤序号（高亮），默认按登录角色推断 */
  highlightSeqs?: number[]
  /** 当前有「我的待办」的步骤名（进行中锚点，与首页待办卡打通） */
  activeStepNames?: string[]
}>(), { highlightSeqs: () => [], activeStepNames: () => [] })

const router = useRouter()
const auth = useAuthStore()
const highlight = computed(() => new Set(props.highlightSeqs))
const activeNames = computed(() => new Set(props.activeStepNames))

/** 本角色泳道（任一高亮步骤所在泳道整条高亮） */
const mineLane = computed(() => {
  const roles = FLOW_LANES.filter((l) => l.steps.some((s) => highlight.value.has(s.seq)))
  return new Set(roles.map((l) => l.role))
})

/** 节点是否可点：角色白名单 + 「显示全部菜单」逃生口，口径与路由守卫一致 */
function allowed(route: string): boolean {
  return isMenuAllowed(auth.role, route, readShowAllMenus())
}

/** 该步骤是否有我的待办（按步骤名或标准模板别名匹配） */
function isActive(s: FlowStep): boolean {
  if (activeNames.value.has(s.name)) return true
  return (s.aliases?.some((a) => activeNames.value.has(a)) ?? false)
}

function kindIcon(s: FlowStep) {
  return s.kind === 'doc' ? FileText : Zap
}

function go(route: string) {
  if (allowed(route)) router.push(route)
}

/** 悬停提示：这一步做什么 + 标准模板细分 + 待办提示 + 无权提示 */
function tooltip(s: FlowStep): string {
  let t = s.desc
  if (s.aliases?.length) t += `。标准模板细分：${s.aliases.join(' / ')}`
  if (isActive(s)) t += '。有你的待办，点此进入'
  if (!allowed(s.route)) t += `。（本步骤由${roleName(s.role)}办理，你的角色无此页面权限）`
  return t
}
</script>

<template>
  <div class="flow-map">
    <div
      v-for="(lane, li) in FLOW_LANES" :key="lane.role"
      class="lane" :class="{ mine: mineLane.has(lane.role) }"
    >
      <div class="lane-head">
        <span class="lane-title">{{ roleName(lane.role) }}</span>
        <span class="lane-sub">{{ lane.subtitle }}</span>
        <span v-if="mineLane.has(lane.role)" class="lane-mine">你负责</span>
      </div>
      <div class="lane-steps">
        <template v-for="(s, i) in lane.steps" :key="s.seq">
          <n-tooltip trigger="hover" placement="bottom">
            <template #trigger>
              <div
                class="flow-node"
                :class="{ doc: s.kind === 'doc', mine: highlight.has(s.seq), disabled: !allowed(s.route), active: isActive(s) }"
                @click="go(s.route)"
              >
                <span class="seq">{{ s.seq }}</span>
                <n-icon :size="13" class="kind-icon"><component :is="kindIcon(s)" /></n-icon>
                <span class="name">{{ s.name }}</span>
                <span v-if="isActive(s)" class="pulse" title="有你的待办" />
                <Lock v-if="!allowed(s.route)" :size="12" class="lock" />
              </div>
            </template>
            <div style="max-width:260px">{{ tooltip(s) }}</div>
          </n-tooltip>
          <ChevronRight v-if="i < lane.steps.length - 1" :size="14" class="arrow" />
        </template>
      </div>
      <div v-if="li < FLOW_LANES.length - 1" class="handoff">
        <ChevronDown :size="16" />
        <span class="handoff-text">交给下一位</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.flow-map {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.lane {
  border-radius: 10px;
  padding: 8px 10px;
  border: 1px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}
.lane.mine {
  background: #FFFBEB;
  border-color: #FDE68A;
}
.lane-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}
.lane-title { font-size: 13px; font-weight: 700; color: #334155; }
.lane-sub { font-size: 12px; color: #94A3B8; }
.lane-mine {
  font-size: 11px; color: #B45309; background: #FEF3C7;
  padding: 1px 8px; border-radius: 10px; font-weight: 600;
}
.lane-steps {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 2px;
}
.flow-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  background: #FFFFFF;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
  user-select: none;
}
.flow-node:hover { border-color: #B45309; box-shadow: 0 1px 4px rgba(180, 83, 9, 0.15); }
.flow-node.mine { border-color: #B45309; background: #FFFBEB; }
.flow-node.active { border-color: #F59E0B; box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.25); }
.flow-node.disabled { opacity: 0.55; cursor: not-allowed; }
.flow-node.disabled:hover { border-color: #E2E8F0; box-shadow: none; }
.seq {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  background: #B45309; color: #fff; font-size: 12px; font-weight: 600;
  flex: none;
}
.flow-node.doc .seq { background: #94A3B8; }
.kind-icon { flex: none; color: #B45309; }
.flow-node.doc .kind-icon { color: #64748B; }
.name { font-size: 13px; font-weight: 500; white-space: nowrap; }
.lock { color: #94A3B8; flex: none; }
.arrow { color: #CBD5E1; flex: none; }
/* 进行中待办脉冲点（纯视觉，不产生可被 e2e 撞到的文本节点） */
.pulse {
  width: 8px; height: 8px; border-radius: 50%;
  background: #F59E0B; flex: none;
  animation: pulse 1.6s ease-out infinite;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.55); }
  70% { box-shadow: 0 0 0 7px rgba(245, 158, 11, 0); }
  100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
}
.handoff {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: center;
  color: #CBD5E1;
  padding: 2px 0;
}
.handoff-text { font-size: 11px; color: #CBD5E1; }
</style>
