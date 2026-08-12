import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { isMenuAllowed, readShowAllMenus } from '../utils/roleMenu'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', name: 'home', component: () => import('../views/Dashboard.vue') },
        { path: 'portfolio', name: 'portfolio', component: () => import('../views/PortfolioView.vue') },
        { path: 'comparison', name: 'comparison', component: () => import('../views/ComparisonView.vue') },
        { path: 'capital', name: 'capital', component: () => import('../views/CapitalView.vue') },
        { path: 'invoices', name: 'invoices', component: () => import('../views/InvoicesView.vue') },
        { path: 'leasing', name: 'leasing', component: () => import('../views/LeasingView.vue') },
        { path: 'profit', name: 'profit', component: () => import('../views/ProfitView.vue') },
        { path: 'sales-orders', name: 'sales-orders', component: () => import('../views/SalesOrdersView.vue') },
        { path: 'devices', name: 'devices', component: () => import('../views/DevicesView.vue') },
        { path: 'acceptances', name: 'acceptances', component: () => import('../views/AcceptancesView.vue') },
        { path: 'confirmations', name: 'confirmations', component: () => import('../views/ConfirmationsView.vue') },
        { path: 'billing', name: 'billing', component: () => import('../views/BillingsView.vue') },
        { path: 'customer-statement', name: 'customer-statement', component: () => import('../views/CustomerStatementView.vue') },
        { path: 'ebs', name: 'ebs', component: () => import('../views/EbsMonitor.vue') },
        { path: 'exchange-rates', name: 'exchange-rates', component: () => import('../views/ExchangeRateView.vue') },
        { path: 'insurance', name: 'insurance', component: () => import('../views/InsuranceView.vue') },
        { path: 'prepayments', name: 'prepayments', component: () => import('../views/PrepaymentView.vue') },
        { path: 'payments', name: 'payments', component: () => import('../views/PaymentView.vue') },
        { path: 'projects/:id/workspace', name: 'workspace', component: () => import('../views/ProjectWorkspace.vue') },
        { path: 'master/:module', name: 'crud', component: () => import('../views/CrudPage.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.token) return { name: 'login' }
  // 角色化菜单守卫：直接输 URL 访问本角色无权的页面 → 回首页（防「菜单没了但 URL 还能进」的困惑）。
  // 工作台对所有登录角色放行：首页待办「立即处理」直达 + 抽屉办理不挑角色。
  if (to.meta.requiresAuth && auth.token && to.name !== 'workspace') {
    if (!isMenuAllowed(auth.role, to.path, readShowAllMenus())) return { path: '/' }
  }
})

export default router
