<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NBreadcrumb, NBreadcrumbItem, NButton, NBadge, NDropdown, NIcon, NLayout, NLayoutContent,
  NLayoutHeader, NMenu, NPopover,
} from 'naive-ui'
import {
  Bell, Boxes, Briefcase, Building2, CheckCheck, ChevronLeft, ChevronRight, ClipboardCheck, ClipboardList, Coins, Cpu,
  Eye, EyeOff,
  FileSignature, FileText, FolderKanban, GitCompareArrows, HelpCircle, Landmark, LayoutDashboard, LogOut, Package, Receipt,
  Share2, ShieldCheck, ShoppingCart, TrendingUp, User, Users, Wallet,
  BadgeCheck, BookCheck, PackageX, PiggyBank, Scale,
  Server,
} from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { roleName } from '../utils/role'
import { isMenuAllowed, readShowAllMenus, writeShowAllMenus } from '../utils/roleMenu'
import { api } from '../api/client'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const collapsed = ref(false)

// 角色化菜单：非管理员/非总监默认只看本角色菜单，顶栏「显示全部」逃生口供一人多角临时展开。
const showAllMenus = ref(readShowAllMenus())
function toggleShowAll() {
  showAllMenus.value = !showAllMenus.value
  writeShowAllMenus(showAllMenus.value)
}

function renderIcon(icon: any) {
  return () => h(NIcon, { size: 18 }, { default: () => h(icon) })
}

const allMenuOptions = [
  { label: '首页', key: '/', icon: renderIcon(LayoutDashboard) },
  { label: '项目总览', key: '/portfolio', icon: renderIcon(FolderKanban) },
  { label: '资金池', key: '/capital', icon: renderIcon(Wallet) },
  { label: '发票/对账', key: '/invoices', icon: renderIcon(FileText) },
  { label: '金租流程', key: '/leasing', icon: renderIcon(Briefcase) },
  { label: '利润测算', key: '/profit', icon: renderIcon(TrendingUp) },
  { label: '项目对比', key: '/comparison', icon: renderIcon(GitCompareArrows) },
  { label: '销售订单', key: '/sales-orders', icon: renderIcon(ShoppingCart) },
  { label: '验收管理', key: '/acceptances', icon: renderIcon(CheckCheck) },
  { label: '客户确认', key: '/confirmations', icon: renderIcon(ClipboardCheck) },
  { label: '计费管理', key: '/billing', icon: renderIcon(Receipt) },
  { label: '客户对账单', key: '/customer-statement', icon: renderIcon(ClipboardList) },
  { label: 'EBS 监控', key: '/ebs', icon: renderIcon(Share2) },
  { label: '币种汇率', key: '/exchange-rates', icon: renderIcon(Coins) },
  { label: '保险管理', key: '/insurance', icon: renderIcon(ShieldCheck) },
  { label: '预付款', key: '/prepayments', icon: renderIcon(PiggyBank) },
  { label: '付款管控', key: '/payments', icon: renderIcon(BadgeCheck) },
  { label: '收入确认', key: '/revenue-recognitions', icon: renderIcon(BookCheck) },
  { label: '对账中心', key: '/reconciliation-center', icon: renderIcon(Scale) },
  { label: '退货管理', key: '/returns', icon: renderIcon(PackageX) },
  { label: '主数据', key: 'g1', type: 'group' as const, children: [
    { label: '供应商', key: '/master/suppliers', icon: renderIcon(Building2) },
    { label: '客户', key: '/master/customers', icon: renderIcon(Users) },
    { label: '设备型号', key: '/master/equipment', icon: renderIcon(Cpu) },
    { label: '银行', key: '/master/banks', icon: renderIcon(Landmark) },
  ] },
  { label: '业务', key: 'g2', type: 'group' as const, children: [
    { label: '项目', key: '/master/projects', icon: renderIcon(FolderKanban) },
    { label: '合同', key: '/master/contracts', icon: renderIcon(FileSignature) },
    { label: '订单', key: '/master/orders', icon: renderIcon(Package) },
    { label: '设备清单', key: '/devices', icon: renderIcon(Server) },
    { label: '资产', key: '/master/assets', icon: renderIcon(Boxes) },
  ] },
]

// 按角色过滤菜单：叶子项查 isMenuAllowed；分组仅当有可见子项时保留（过滤其 children）。
// 泛型 T 保留原始字面量类型推断，保证 n-menu :options 类型兼容。
function filterMenu<T extends { key: string; type?: string; children?: readonly T[] }>(
  items: readonly T[],
): T[] {
  const out: T[] = []
  for (const item of items) {
    if (item.type === 'group') {
      const children = item.children ? filterMenu(item.children) : []
      if (children.length) out.push({ ...item, children } as T)
    } else if (isMenuAllowed(auth.role, item.key, showAllMenus.value)) {
      out.push(item)
    }
  }
  return out
}

const visibleMenuOptions = computed(() => filterMenu(allMenuOptions))
// 仅被过滤的角色（非管理员/非总监）才显示「显示全部」逃生口按钮
const showRoleToggle = computed(() => auth.role !== 'ADMIN' && auth.role !== 'FINANCE_DIRECTOR')

const TITLE_MAP: Record<string, string> = {
  '/': '首页',
  '/portfolio': '项目总览',
  '/capital': '资金池',
  '/invoices': '发票 / 对账',
  '/leasing': '金租流程',
  '/profit': '利润测算',
  '/comparison': '项目对比',
  '/sales-orders': '销售订单',
  '/devices': '设备清单',
  '/acceptances': '验收管理',
  '/confirmations': '客户确认',
  '/billing': '计费管理',
  '/customer-statement': '客户对账单',
  '/ebs': 'EBS 监控',
  '/exchange-rates': '币种与汇率',
  '/insurance': '保险管理',
  '/prepayments': '预付款台账',
  '/payments': '付款管控',
  '/revenue-recognitions': '收入确认',
  '/reconciliation-center': '对账中心',
  '/returns': '退货管理',
  '/master/suppliers': '供应商',
  '/master/customers': '客户',
  '/master/equipment': '设备型号',
  '/master/banks': '银行',
  '/master/projects': '项目',
  '/master/contracts': '合同',
  '/master/orders': '订单',
  '/master/assets': '资产',
}

const activeKey = computed(() => route.path)
const currentTitle = computed(() => TITLE_MAP[route.path] || '业务')

function onSelect(key: string) {
  if (key.startsWith('/')) router.push(key)
}

function logout() {
  auth.logout()
  router.push('/login')
}

const userOptions = [{ label: '退出登录', key: 'logout', icon: renderIcon(LogOut) }]
function onUserMenu(key: string) {
  if (key === 'logout') logout()
}

// —— 应用内消息提醒（F1）：顶栏铃铛 + 红点，30s 静默轮询，点击跳转并标已读 ——
interface NotifItem {
  id: string; kind: string; ref_type: string | null; ref_id: string | null
  title: string; body: string; level: string
  read_at: string | null; created_at: string | null
}
const notifList = ref<NotifItem[]>([])
const unreadCount = computed(() => notifList.value.filter(n => !n.read_at).length)
const showNotif = ref(false)

async function fetchNotifs() {
  try {
    const r = await api.get('/notifications')
    notifList.value = r.data.items || []
  } catch { /* 静默轮询失败不打扰 */ }
}
// ref_type → 可跳转的列表页（一期按类别跳，不深挖单据详情）
const REF_ROUTE: Record<string, string> = {
  repayment: '/capital', capital: '/capital', leasing: '/leasing',
  delivery: '/devices', contract: '/master/contracts', project: '/portfolio',
}
function levelColor(level: string) {
  return level === '高危' ? '#dc2626' : level === '警告' ? '#d97706' : '#2563eb'
}
async function clickNotif(n: NotifItem) {
  if (!n.read_at) {
    n.read_at = new Date().toISOString()  // 乐观更新
    try { await api.post(`/notifications/${n.id}/read`) } catch { /* 静默 */ }
  }
  showNotif.value = false
  const route = n.ref_type ? REF_ROUTE[n.ref_type] : undefined
  if (route) router.push(route)
}
async function readAllNotifs() {
  try {
    await api.post('/notifications/read-all')
    notifList.value.forEach(n => { if (!n.read_at) n.read_at = new Date().toISOString() })
  } catch { /* 静默 */ }
}
let notifTimer: number | undefined
onMounted(() => {
  fetchNotifs()
  notifTimer = window.setInterval(fetchNotifs, 30000)
})
onUnmounted(() => { if (notifTimer !== undefined) window.clearInterval(notifTimer) })
</script>

<template>
  <n-layout has-sider style="height:100vh">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand">
        <span class="brand-mark">S</span>
        <span v-if="!collapsed" class="brand-text">SIEGPU</span>
      </div>
      <n-menu
        :options="visibleMenuOptions"
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="18"
        inverted
        @update:value="onSelect"
      />
      <button class="collapse-btn" @click="collapsed = !collapsed">
        <n-icon size="16"><component :is="collapsed ? ChevronRight : ChevronLeft" /></n-icon>
        <span v-if="!collapsed" class="tiny">收起</span>
      </button>
    </aside>

    <n-layout>
      <n-layout-header bordered class="topbar">
        <n-breadcrumb>
          <n-breadcrumb-item>SIEGPU ERP</n-breadcrumb-item>
          <n-breadcrumb-item>{{ currentTitle }}</n-breadcrumb-item>
        </n-breadcrumb>
        <div class="topbar-actions">
          <n-button
            v-if="showRoleToggle"
            quaternary
            size="small"
            :type="showAllMenus ? 'primary' : 'default'"
            :title="showAllMenus ? '正在显示全部菜单，点击只看我角色的' : '只看我角色的菜单，点击显示全部'"
            @click="toggleShowAll"
          >
            <template #icon>
              <n-icon><component :is="showAllMenus ? EyeOff : Eye" /></n-icon>
            </template>
            {{ showAllMenus ? '全部菜单' : '我的角色' }}
          </n-button>
          <n-popover v-model:show="showNotif" trigger="click" placement="bottom-end" :width="320">
            <template #trigger>
              <n-badge :value="unreadCount" :max="99" :offset="[-4, 4]" :show="unreadCount > 0">
                <n-button quaternary size="small" aria-label="消息提醒" title="消息提醒">
                  <template #icon><n-icon><Bell /></n-icon></template>
                </n-button>
              </n-badge>
            </template>
            <div style="width:300px">
              <div style="display:flex;align-items:center;justify-content:space-between;padding:2px 2px 8px;border-bottom:1px solid var(--c-border,#eee)">
                <span style="font-weight:600">消息提醒</span>
                <n-button v-if="unreadCount > 0" text size="tiny" type="primary" @click="readAllNotifs">全部已读</n-button>
              </div>
              <div v-if="notifList.length === 0" style="padding:28px 0;text-align:center;color:var(--c-text-light,#999);font-size:13px">暂无消息</div>
              <div v-else style="max-height:360px;overflow:auto">
                <div
                  v-for="n in notifList" :key="n.id"
                  style="display:flex;gap:8px;padding:10px 4px;cursor:pointer;border-bottom:1px solid var(--c-border,#f0f0f0)"
                  @click="clickNotif(n)"
                >
                  <span :style="{ flex:'none', width:'8px', height:'8px', borderRadius:'50%', marginTop:'5px', background: levelColor(n.level), opacity: n.read_at ? 0.25 : 1 }"></span>
                  <div style="flex:1;min-width:0">
                    <div :style="{ fontSize:'13px', fontWeight: n.read_at ? 400 : 600, color: n.read_at ? 'var(--c-text-light,#999)' : 'inherit' }">{{ n.title }}</div>
                    <div style="font-size:12px;color:var(--c-text-light,#888);margin-top:2px;line-height:1.5">{{ n.body }}</div>
                  </div>
                </div>
              </div>
            </div>
          </n-popover>
          <n-popover trigger="click" placement="bottom-end" style="max-width:320px">
            <template #trigger>
              <n-button quaternary size="small" aria-label="帮助">
                <template #icon><n-icon><HelpCircle /></n-icon></template>
              </n-button>
            </template>
            <div style="font-size:12px;line-height:1.9">
              <div style="font-weight:600;margin-bottom:4px">术语表</div>
              <div><b>点亮</b>：设备正式投产上线，点亮日为计费起点</div>
              <div><b>红冲</b>：作废单据并生成红字反向凭证，对账自动剔除</div>
              <div><b>金租置换</b>：金租放款后自动归还原流贷/自有垫付资金</div>
              <div><b>三流对账</b>：合同流/发票流/资金流交叉核对</div>
              <div><b>等额本息</b>：每期还款额固定的还款方式</div>
            </div>
          </n-popover>
          <n-dropdown :options="userOptions" trigger="click" @select="onUserMenu">
            <n-button quaternary size="small">
              <template #icon><n-icon><User /></n-icon></template>
              {{ auth.displayName }} · {{ roleName(auth.role) }}
            </n-button>
          </n-dropdown>
        </div>
      </n-layout-header>

      <n-layout-content class="content" content-style="padding:20px">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<style scoped>
.sidebar {
  width: 220px;
  background: var(--c-sidebar-bg);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  color: var(--c-sidebar-text);
  border-right: 1px solid var(--c-sidebar-bg-2);
}
.sidebar.collapsed { width: 64px; }
.brand {
  display: flex; align-items: center; gap: 10px;
  padding: 16px 18px; height: 56px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.brand-mark {
  width: 28px; height: 28px; border-radius: 8px; flex: none;
  background: var(--c-primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-heading); font-weight: 700; font-size: 15px;
}
.brand-text { font-family: var(--font-heading); font-weight: 700; color: #fff; letter-spacing: .04em; }
/* 菜单可能很多项（含两个分组 + EBS），超过视口时菜单区独立滚动，brand / 收起按钮固定不动。
   min-height:0 是关键：flex 子项默认 min-height:auto 会被内容撑高，不加它 overflow 不生效、底部项被裁够不着。 */
.sidebar :deep(.n-menu) {
  background: transparent;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
  scrollbar-width: thin;                                            /* Firefox */
  scrollbar-color: rgba(255,255,255,0.18) transparent;
}
/* 暗色侧栏原生滚动条美化，避免亮色滚动条刺眼（Webkit: Chrome/Edge/Safari） */
.sidebar :deep(.n-menu)::-webkit-scrollbar { width: 6px; }
.sidebar :deep(.n-menu)::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }
.sidebar :deep(.n-menu)::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.22); }
.sidebar :deep(.n-menu)::-webkit-scrollbar-track { background: transparent; }
.sidebar :deep(.n-menu-item-content) { color: var(--c-sidebar-text); border-radius: 8px; }
.sidebar :deep(.n-menu-item-content:hover) { background: var(--c-sidebar-hover); }
.sidebar :deep(.n-menu-item-content--selected) {
  background: var(--c-sidebar-active); color: var(--c-sidebar-text-active);
  box-shadow: inset 3px 0 0 var(--c-primary);
}
.sidebar :deep(.n-menu-item-content--selected .n-icon) { color: var(--c-primary); }
.sidebar :deep(.n-menu-item-content--selected .n-menu-item-content-header) { color: var(--c-sidebar-text-active); }
.collapse-btn {
  display: flex; align-items: center; gap: 8px;
  margin: 8px 12px 14px; padding: 8px 10px;
  background: transparent; border: 1px solid rgba(255,255,255,0.08);
  color: var(--c-sidebar-text); border-radius: 8px; cursor: pointer;
}
.collapse-btn:hover { background: var(--c-sidebar-hover); color: #fff; }
.topbar {
  height: 56px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 20px; background: var(--c-surface);
}
.topbar-actions { display: flex; align-items: center; gap: 4px; }
.content { background: var(--c-bg); }
</style>
