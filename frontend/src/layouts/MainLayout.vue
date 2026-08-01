<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NBreadcrumb, NBreadcrumbItem, NButton, NDropdown, NIcon, NLayout, NLayoutContent,
  NLayoutHeader, NMenu, NPopover,
} from 'naive-ui'
import {
  Boxes, Briefcase, Building2, CheckCheck, ChevronLeft, ChevronRight, ClipboardCheck, Cpu,
  FileSignature, FileText, FolderKanban, GitCompareArrows, HelpCircle, Landmark, LayoutDashboard, LogOut, Package, Receipt,
  ShoppingCart, TrendingUp, User, Users, Wallet,
} from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { roleName } from '../utils/role'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const collapsed = ref(false)

function renderIcon(icon: any) {
  return () => h(NIcon, { size: 18 }, { default: () => h(icon) })
}

const menuOptions = [
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
    { label: '资产', key: '/master/assets', icon: renderIcon(Boxes) },
  ] },
]

const TITLE_MAP: Record<string, string> = {
  '/': '首页',
  '/portfolio': '项目总览',
  '/capital': '资金池',
  '/invoices': '发票 / 对账',
  '/leasing': '金租流程',
  '/profit': '利润测算',
  '/comparison': '项目对比',
  '/sales-orders': '销售订单',
  '/acceptances': '验收管理',
  '/confirmations': '客户确认',
  '/billing': '计费管理',
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
</script>

<template>
  <n-layout has-sider style="height:100vh">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand">
        <span class="brand-mark">S</span>
        <span v-if="!collapsed" class="brand-text">SIEGPU</span>
      </div>
      <n-menu
        :options="menuOptions"
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
.sidebar :deep(.n-menu) { background: transparent; flex: 1; padding: 8px; }
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
.content { background: var(--c-bg); }
</style>
