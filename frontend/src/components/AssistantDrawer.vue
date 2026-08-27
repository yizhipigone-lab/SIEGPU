<script setup lang="ts">
/**
 * 智能助手侧边栏（Ctrl+J）——右侧抽屉式对话，对本系统做只读智能分析。
 *
 * - 不遮罩（:mask="false"），边聊边操作主区；宽度 540px。
 * - SSE 消费：fetch + ReadableStream 手动解析 data: 行（EventSource 不支持 POST + JWT header）。
 * - 体验包（2026-08-27）：agent 工具轮显示「正在查：XX」进度行；done.links 渲染跳页按钮；
 *   助手消息带 👍/👎 反馈（👎 落问题缺口表，驱动补工具/补 KB）。
 * - 低置信标记只是展示层（后端不入库，防模型从历史里学坏）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NDrawer, NDrawerContent, NIcon, NInput, NSpin, NTag, NTooltip } from 'naive-ui'
import { Bot, Eraser, SendHorizonal, ThumbsDown, ThumbsUp } from 'lucide-vue-next'

const props = defineProps<{ show: boolean; pageContext?: string }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const route = useRoute()
const router = useRouter()

interface Link { label: string; route: string }
interface ConfirmCard {
  kind: 'confirm'; token_id: string; action: string; label: string
  params: Record<string, any>; impact_amount: number | null; impact_desc: string
  warnings: string[]; expires_in_minutes: number
  status?: 'pending' | 'done' | 'failed' | 'cancelled' | 'expired'
  message?: string
}
interface Msg {
  id?: string
  role: 'user' | 'assistant'
  content: string
  lowConfidence?: boolean
  pending?: boolean
  progress?: string[]
  links?: Link[]
  feedback?: 'up' | 'down' | null
  cards?: ConfirmCard[]
}

const messages = ref<Msg[]>([])
const input = ref('')
const sending = ref(false)
const quotaLeft = ref<number | null>(null)
const listRef = ref<HTMLElement | null>(null)

const QUICK_QUESTIONS = [
  '现在资金池还有多少头寸？',
  '有没有逾期的还款？',
  '点亮是什么意思？',
  '月结要做什么？',
]

const visible = computed({
  get: () => props.show,
  set: (v: boolean) => emit('update:show', v),
})

function token(): string {
  return localStorage.getItem('token') || ''
}

async function loadHistory() {
  try {
    const r = await fetch('/api/assistant/history', { headers: { Authorization: `Bearer ${token()}` } })
    if (!r.ok) return
    const data = await r.json()
    quotaLeft.value = data.quota_left ?? null
    messages.value = (data.messages || []).map((m: any) => ({
      id: m.id, role: m.role, content: m.content, feedback: m.feedback ?? null,
      progress: [],
    }))
    scrollBottom()
  } catch { /* 静默：历史加载失败不影响提问 */ }
}

watch(() => props.show, (v) => { if (v && messages.value.length === 0) loadHistory() })

function scrollBottom() {
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

/** 轻量 markdown：**加粗** 与 | 表格 | 行 → HTML（转义在先，防 XSS）。 */
function renderMd(text: string): string {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const lines = esc(text).split('\n')
  const out: string[] = []
  let inTable = false
  for (const line of lines) {
    const isRow = /^\|.*\|$/.test(line.trim())
    if (isRow && !inTable) { out.push('<table class="md-table">'); inTable = true }
    if (!isRow && inTable) { out.push('</table>'); inTable = false }
    if (isRow) {
      const cells = line.trim().slice(1, -1).split('|').map(c => c.trim())
      if (cells.every(c => /^:?-+:?$/.test(c))) continue
      out.push('<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>')
    } else if (line.trim()) {
      out.push('<div>' + line.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>') + '</div>')
    } else {
      out.push('<div style="height:6px"></div>')
    }
  }
  if (inTable) out.push('</table>')
  return out.join('')
}

async function send(q?: string) {
  const question = (q ?? input.value).trim()
  if (!question || sending.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: question })
  const bot: Msg = { role: 'assistant', content: '', pending: true, progress: [] }
  messages.value.push(bot)
  sending.value = true
  scrollBottom()
  try {
    const r = await fetch('/api/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
      body: JSON.stringify({
        question,
        page_context: props.pageContext || `${String(route.name || '')} ${route.path}`.trim(),
      }),
    })
    const newToken = r.headers.get('x-token-refresh')
    if (newToken) localStorage.setItem('token', newToken)
    if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`)
    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const events = buf.split('\n\n')
      buf = events.pop() || ''
      for (const ev of events) {
        const line = ev.split('\n').find(l => l.startsWith('data:'))
        if (!line) continue
        try {
          const data = JSON.parse(line.slice(5).trim())
          if (data.type === 'delta') { bot.content += data.text; scrollBottom() }
          else if (data.type === 'progress') {
            if (bot.progress && !bot.progress.includes(data.text)) bot.progress.push(data.text)
            scrollBottom()
          } else if (data.type === 'card' && data.card) {
            bot.cards = [...(bot.cards || []), { ...data.card, status: 'pending' as const }]
            scrollBottom()
          } else if (data.type === 'done') {
            bot.lowConfidence = !!data.low_confidence
            bot.links = data.links || []
            bot.id = data.message_id
            quotaLeft.value = data.quota_left ?? quotaLeft.value
          } else if (data.type === 'error') { bot.content = bot.content || `⚠️ ${data.message}` }
        } catch { /* 半包 JSON，等下一段 */ }
      }
    }
    if (!bot.content) bot.content = '（助手没有返回内容，请换个问法再试）'
  } catch (e: any) {
    bot.content = `⚠️ 助手暂时不可用：${e?.message || '网络异常'}。系统其他功能不受影响。`
  } finally {
    bot.pending = false
    sending.value = false
    scrollBottom()
  }
}

async function sendFeedback(m: Msg, value: 'up' | 'down') {
  if (m.feedback === value) return
  m.feedback = value
  if (!m.id) return
  // 👎 带上问题原文落缺口表（找它前面的那条用户消息）
  const idx = messages.value.indexOf(m)
  const question = idx > 0 && messages.value[idx - 1].role === 'user'
    ? messages.value[idx - 1].content : undefined
  try {
    await fetch('/api/assistant/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
      body: JSON.stringify({ message_id: m.id, value, question }),
    })
  } catch { /* 静默：反馈失败不影响对话 */ }
}

async function resetChat() {
  try {
    await fetch('/api/assistant/reset', { method: 'POST', headers: { Authorization: `Bearer ${token()}` } })
  } catch { /* 静默 */ }
  messages.value = []
}

async function confirmCard(m: Msg, card: ConfirmCard) {
  if (card.status && card.status !== 'pending') return
  try {
    const r = await fetch('/api/assistant/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
      body: JSON.stringify({ token_id: card.token_id }),
    })
    const data = await r.json()
    card.status = data.ok ? 'done' : (data.status === 410 ? 'expired' : 'failed')
    card.message = data.message || ''
  } catch (e: any) {
    card.status = 'failed'; card.message = e?.message || '网络异常'
  }
}

async function cancelCard(m: Msg, card: ConfirmCard) {
  if (card.status && card.status !== 'pending') return
  try {
    await fetch('/api/assistant/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
      body: JSON.stringify({ token_id: card.token_id }),
    })
  } catch { /* 静默 */ }
  card.status = 'cancelled'; card.message = '已取消'
}

function statusText(s?: string): string {
  return ({ pending: '待确认', done: '✅ 已执行', failed: '❌ 失败', cancelled: '已取消', expired: '⏰ 已过期' } as Record<string, string>)[s || 'pending'] || ''
}

function go(l: Link) {
  router.push(l.route)
}

function onEnter(e: KeyboardEvent) {
  if (!e.shiftKey) { e.preventDefault(); send() }
}
</script>

<template>
  <n-drawer v-model:show="visible" :width="540" placement="right" :mask="false" to="body"
            class="assistant-drawer" data-testid="assistant-drawer">
    <n-drawer-content closable body-content-style="padding:0;display:flex;flex-direction:column">
      <template #header>
        <div style="display:flex;align-items:center;gap:8px">
          <n-icon size="18" color="#2563eb"><Bot /></n-icon>
          <span>AI 老虎</span>
          <n-tag v-if="quotaLeft !== null" size="tiny" :bordered="false" type="info">
            今日额度 {{ Math.round(quotaLeft / 1000) }}k
          </n-tag>
        </div>
      </template>
      <template #footer>
        <div style="display:flex;gap:8px;align-items:flex-end">
          <n-input
            v-model:value="input" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }"
            placeholder="问数据、问流程、问操作…（Enter 发送）"
            :disabled="sending" @keydown.enter="onEnter"
          />
          <n-button type="primary" :disabled="sending || !input.trim()" @click="send()">
            <template #icon><n-icon><SendHorizonal /></n-icon></template>
          </n-button>
          <n-tooltip>
            <template #trigger>
              <n-button quaternary @click="resetChat">
                <template #icon><n-icon><Eraser /></n-icon></template>
              </n-button>
            </template>
            新对话（清空当前会话）
          </n-tooltip>
        </div>
      </template>

      <div ref="listRef" class="msg-list">
        <div v-if="pageContext" class="ctx-chip">📍 当前页面：{{ pageContext }}</div>
        <div v-if="messages.length === 0" class="empty">
          <p>我是系统的只读智能助手，可以帮你：</p>
          <ul>
            <li>查数据：资金头寸 / 还款 / 开票 / 预警</li>
            <li>讲流程：11 步主链路 / 术语 / 月结</li>
            <li>做分析：三流对账差异 / 项目总览</li>
            <li>自由查：18 类业务数据我可以自己组合条件查</li>
          </ul>
          <div class="quick">
            <n-button v-for="q in QUICK_QUESTIONS" :key="q" size="small" tertiary @click="send(q)">{{ q }}</n-button>
          </div>
        </div>
        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="bubble-wrap">
            <div class="bubble">
              <div v-if="m.progress && m.progress.length" class="progress-line">
                <div v-for="(p, j) in m.progress" :key="j">🔍 {{ p }}</div>
              </div>
              <span v-if="m.role === 'user'">{{ m.content }}</span>
              <!-- 助手内容由后端 SSE 产生，renderMd 先转义再渲染，无 XSS 面 -->
              <span v-else v-html="renderMd(m.content)"></span>
              <n-spin v-if="m.pending && !m.content" size="small" style="margin-top:4px" />
              <div v-if="m.lowConfidence" class="low-conf">⚠️ 低置信：部分数字未溯源到系统数据，请核实</div>
            </div>
            <div v-for="card in m.cards || []" :key="card.token_id" class="confirm-card">
              <div class="cc-head">
                <span class="cc-badge">{{ card.label }}</span>
                <span class="cc-status" :class="card.status">{{ statusText(card.status) }}</span>
              </div>
              <table class="cc-params">
                <tr v-for="(v, k) in card.params" :key="k"><td>{{ k }}</td><td>{{ v ?? '—' }}</td></tr>
              </table>
              <div v-if="card.impact_amount !== null" class="cc-amount">¥ {{ card.impact_amount.toLocaleString() }}</div>
              <div class="cc-desc">{{ card.impact_desc }}</div>
              <div v-for="(w, j) in card.warnings" :key="j" class="cc-warn">⚠️ {{ w }}</div>
              <div v-if="card.status === 'pending'" class="cc-actions">
                <n-button size="tiny" type="primary" @click="confirmCard(m, card)">确认执行</n-button>
                <n-button size="tiny" quaternary @click="cancelCard(m, card)">取消</n-button>
                <span class="cc-ttl">{{ card.expires_in_minutes }} 分钟内有效</span>
              </div>
              <div v-if="card.message" class="cc-msg">{{ card.message }}</div>
            </div>
            <div v-if="m.role === 'assistant' && !m.pending" class="msg-actions">
              <n-button
                v-for="l in m.links || []" :key="l.route"
                size="tiny" tertiary type="primary" @click="go(l)"
              >去{{ l.label }} →</n-button>
              <n-button
                size="tiny" quaternary :type="m.feedback === 'up' ? 'success' : 'default'"
                aria-label="有用" @click="sendFeedback(m, 'up')"
              ><template #icon><n-icon size="13"><ThumbsUp /></n-icon></template></n-button>
              <n-button
                size="tiny" quaternary :type="m.feedback === 'down' ? 'error' : 'default'"
                aria-label="没用" @click="sendFeedback(m, 'down')"
              ><template #icon><n-icon size="13"><ThumbsDown /></n-icon></template></n-button>
            </div>
          </div>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.msg-list { flex: 1; overflow-y: auto; padding: 16px; max-height: calc(100vh - 200px); }
.ctx-chip {
  font-size: 12px; color: #475569; background: #F1F5F9; border: 1px solid #E2E8F0;
  border-radius: 999px; padding: 3px 10px; display: inline-block; margin-bottom: 10px;
}
.empty { color: #64748B; font-size: 13px; line-height: 1.8; padding: 8px 2px; }
.empty ul { padding-left: 18px; margin: 6px 0 12px; }
.quick { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.msg { display: flex; margin-bottom: 10px; }
.msg.user { justify-content: flex-end; }
.bubble-wrap { max-width: 94%; display: flex; flex-direction: column; gap: 4px; }
.msg.user .bubble-wrap { align-items: flex-end; }
.bubble {
  padding: 10px 14px; border-radius: 10px; font-size: 14px; line-height: 1.75;
  background: #F1F5F9; word-break: break-word;
}
.msg.user .bubble { background: #2563eb; color: #fff; }
.progress-line { font-size: 12px; color: #64748B; margin-bottom: 4px; line-height: 1.6; }
.low-conf {
  margin-top: 6px; font-size: 12px; color: #B45309;
  background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 6px; padding: 4px 8px;
}
.msg-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.confirm-card { border: 1px solid #FDE68A; background: #FFFBEB; border-radius: 8px; padding: 10px 12px; font-size: 13px; }
.cc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.cc-badge { background: #D97706; color: #fff; border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; }
.cc-status { font-size: 12px; color: #64748B; }
.cc-status.done { color: #16A34A; } .cc-status.failed { color: #DC2626; }
.cc-params { border-collapse: collapse; margin: 4px 0; width: 100%; }
.cc-params td { border: 1px solid #FDE68A; padding: 3px 8px; font-size: 12px; }
.cc-params td:first-child { color: #92400E; width: 40%; }
.cc-amount { font-size: 18px; font-weight: 700; color: #B45309; margin: 4px 0; }
.cc-desc { font-size: 12px; color: #64748B; }
.cc-warn { font-size: 12px; color: #B45309; margin-top: 4px; }
.cc-actions { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
.cc-ttl { font-size: 11px; color: #92400E; }
.cc-msg { font-size: 12px; color: #475569; margin-top: 6px; }
.bubble :deep(.md-table) { border-collapse: collapse; margin: 6px 0; font-size: 12px; }
.bubble :deep(.md-table td) { border: 1px solid #CBD5E1; padding: 3px 8px; }
</style>