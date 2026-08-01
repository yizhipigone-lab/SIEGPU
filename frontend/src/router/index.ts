import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

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
        { path: 'acceptances', name: 'acceptances', component: () => import('../views/AcceptancesView.vue') },
        { path: 'confirmations', name: 'confirmations', component: () => import('../views/ConfirmationsView.vue') },
        { path: 'billing', name: 'billing', component: () => import('../views/BillingsView.vue') },
        { path: 'projects/:id/workspace', name: 'workspace', component: () => import('../views/ProjectWorkspace.vue') },
        { path: 'master/:module', name: 'crud', component: () => import('../views/CrudPage.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.token) return { name: 'login' }
})

export default router
