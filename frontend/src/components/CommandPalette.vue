<script setup lang="ts">
/**
 * 命令面板（Ctrl+K / ⌘K）—— 按动作搜索直达页面。
 *
 * - 数据源：commands.ts COMMANDS（title + keywords + route + group）
 * - 权限：无权项置灰显示「需更高权限」，点击无效，与路由守卫口径一致（isMenuAllowed）
 * - 键盘：↑↓ 移动，Enter 跳转，Esc 关闭（NModal 原生）；打开时自动聚焦并清空上次输入
 * - 快捷区（空查询时显示）：收藏 + 最近访问（recents.ts），新手重复走同几页不用重新找
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NInput, NModal, NTag } from 'naive-ui'
import { Clock, CornerDownLeft, Lock, Search, Star } from 'lucide-vue-next'
import { COMMANDS } from '../utils/commands'
import type { CommandItem } from '../utils/commands'
import { favs, isFav, recents, toggleFav } from '../utils/recents'
import { isMenuAllowed, readShowAllMenus } from '../utils/roleMenu'
import { useAuthStore } from '../stores/auth'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const router = useRouter()
const auth = useAuthStore()
const query = ref('')
const active = ref(0)
const inputRef = ref<{ focus: () => void } | null>(null)

type Row = CommandItem & { allowed: boolean }

const results = computed<Row[]>(() => {
  const showAll = readShowAllMenus()
  const all: Row[] = COMMANDS.map((c) => ({
    ...c, allowed: isMenuAllowed(auth.role, c.route, showAll),
  }))
  const q = query.value.trim().toLowerCase()
  if (!q) return all
  // 有权项排前面，置灰项沉底（看得到但不妨碍键盘直达）
  const hit = all.filter((c) =>
    c.title.toLowerCase().includes(q) || c.keywords.some((k) => k.toLowerCase().includes(q)),
  )
  return [...hit.filter((c) => c.allowed), ...hit.filter((c) => !c.allowed)]
})

// —— 快捷区：收藏 + 最近访问（空查询时展示，鼠标直达）——
const favVersion = ref(0)
const favPaths = computed(() => {
  favVersion.value
  return new Set(favs().map((f) => f.path))
})
const favList = computed(() => {
  favVersion.value
  return favs()
})
const recentList = computed(() => recents())
const showQuick = computed(() => !query.value.trim() && (favList.value.length > 0 || recentList.value.length > 0))

function star(c: CommandItem) {
  toggleFav({ path: c.route, title: c.title })
  favVersion.value++
}

watch(() => props.show, async (v) => {
  if (v) {
    query.value = ''
    active.value = 0
    favVersion.value++ // 打开时刷新收藏/最近
    await nextTick()
    inputRef.value?.focus()
  }
})
watch(results, () => { active.value = 0 })

function go(c: Row | undefined) {
  if (!c || !c.allowed) return
  emit('update:show', false)
  router.push(c.route)
}
function goQuick(path: string) {
  emit('update:show', false)
  router.push(path)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    active.value = Math.min(active.value + 1, results.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    active.value = Math.max(active.value - 1, 0)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    go(results.value[active.value])
  }
}
</script>

<template>
  <n-modal
    :show="show" preset="card" style="max-width:560px" :bordered="false"
    title="" @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div @keydown="onKey">
      <n-input
        ref="inputRef" v-model:value="query" size="large"
        placeholder="输入想做的事：开票 / 放款 / 验收 / fk …"
        data-testid="command-input"
      >
        <template #prefix><Search :size="16" style="color:#94A3B8" /></template>
      </n-input>

      <!-- 快捷区：收藏 + 最近访问 -->
      <div v-if="showQuick" class="quick-section">
        <template v-if="favList.length">
          <div class="quick-title">收藏</div>
          <div v-for="f in favList" :key="'fav' + f.path" class="quick-row">
            <button type="button" class="quick-main" :aria-label="'前往' + f.title" @click="goQuick(f.path)">
              <Star :size="13" class="q-star" />
              <span class="q-name">{{ f.title }}</span>
            </button>
            <button type="button" class="q-x" :aria-label="'取消收藏' + f.title" @click="toggleFav(f); favVersion++">取消</button>
          </div>
        </template>
        <template v-if="recentList.length">
          <div class="quick-title">最近访问</div>
          <div v-for="r in recentList" :key="'rec' + r.path" class="quick-row">
            <button type="button" class="quick-main" :aria-label="'前往' + r.title" @click="goQuick(r.path)">
              <Clock :size="13" class="q-clock" />
              <span class="q-name">{{ r.title }}</span>
            </button>
          </div>
        </template>
      </div>

      <div class="result-list">
        <div
          v-for="(c, i) in results" :key="c.route + c.title"
          class="result-row"
          :class="{ active: i === active, disabled: !c.allowed }"
          @mouseenter="active = i"
          @click="go(c)"
        >
          <button
            type="button"
            class="r-star" :class="{ on: favPaths.has(c.route) }"
            :aria-label="(favPaths.has(c.route) ? '取消收藏' : '收藏') + c.title"
            @click.stop="star(c)"
          >
            <Star :size="13" :fill="favPaths.has(c.route) ? 'currentColor' : 'none'" />
          </button>
          <span class="r-title">{{ c.title }}</span>
          <n-tag size="tiny" :bordered="false" class="r-group">{{ c.group }}</n-tag>
          <span v-if="!c.allowed" class="r-lock">
            <Lock :size="12" /> 需更高权限
          </span>
          <CornerDownLeft v-else-if="i === active" :size="13" class="r-enter" />
        </div>
        <div v-if="!results.length" class="r-empty">
          没有匹配「{{ query }}」的页面。试试动作词：开票 / 验收 / 计费 / 放款
        </div>
      </div>

      <div class="hint-bar">
        <span>↑↓ 选择</span><span>Enter 跳转</span><span>Esc 关闭</span>
      </div>
    </div>
  </n-modal>
</template>

<style scoped>
.quick-section {
  margin-top: 12px;
  padding: 4px 4px 8px;
  border-bottom: 1px solid #F1F5F9;
}
.quick-title { font-size: 11px; color: #94A3B8; margin: 6px 4px 2px; }
.quick-row {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 10px; border-radius: 8px;
  font-size: 13px; color: #475569;
}
.quick-row:hover { background: #F8FAFC; }
.quick-main {
  flex: 1; display: flex; align-items: center; gap: 8px;
  background: transparent; border: none; padding: 2px 0;
  font-size: 13px; color: #475569; cursor: pointer; text-align: left;
}
.q-star { color: #B45309; flex: none; }
.q-clock { color: #94A3B8; flex: none; }
.q-name { font-weight: 500; }
.q-x {
  flex: none; background: transparent; border: none; padding: 0;
  font-size: 11px; color: #94A3B8; cursor: pointer;
}
.q-x:hover { color: #475569; }
.result-list { margin-top: 8px; max-height: 340px; overflow-y: auto; }
.result-row {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 12px; border-radius: 8px; cursor: pointer;
}
.result-row.active { background: #FEF3C7; }
.result-row.disabled { opacity: 0.5; cursor: not-allowed; }
.r-star {
  flex: none; color: #CBD5E1; cursor: pointer; display: inline-flex;
  background: transparent; border: none; padding: 0;
}
.r-star.on { color: #F59E0B; }
.r-title { font-size: 14px; font-weight: 500; }
.r-group { margin-left: auto; }
.r-lock { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; color: #94A3B8; }
.r-enter { color: #B45309; }
.r-empty { padding: 32px 0; text-align: center; color: #94A3B8; font-size: 13px; }
.hint-bar {
  display: flex; gap: 16px; margin-top: 12px; padding-top: 10px;
  border-top: 1px solid #F1F5F9; color: #94A3B8; font-size: 12px;
}
</style>
