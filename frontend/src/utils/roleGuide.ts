/**
 * 角色落地引导 —— 角色化首页 + 职责横幅 + 流程图高亮的单一事实源。
 *
 * 依据：workflow_service._device_flow_steps() 的 11 步 doer_role（权威映射）：
 *   采购(PROCUREMENT)  = Step 1-4 项目建立 / 销售合同 / 采购合同 / 批次订单
 *   交付(DELIVERY)     = Step 5-8 设备导入 / 到货 / 上架 / 点亮验收
 *   财务(FINANCE_STAFF)= Step 9-11 金租放款 / 按台计费 / 盈利测算
 * 改这里即可调整某角色的职责文案 / 快捷入口，不动 Dashboard。
 *
 * quickActions.route 必须落在 roleMenu.ts 该角色白名单内，否则路由守卫会拦回首页。
 */
import { roleName } from './role'

/** 11 步流程（与后端 _device_flow_steps 同源，名称逐字对齐） */
export const FLOW_STEPS: ReadonlyArray<{ seq: number; name: string }> = [
  { seq: 1, name: '项目建立' },
  { seq: 2, name: '销售合同' },
  { seq: 3, name: '采购合同' },
  { seq: 4, name: '批次订单' },
  { seq: 5, name: '设备导入' },
  { seq: 6, name: '设备到货' },
  { seq: 7, name: '设备上架' },
  { seq: 8, name: '点亮验收' },
  { seq: 9, name: '金租放款' },
  { seq: 10, name: '按台计费' },
  { seq: 11, name: '盈利测算' },
]

export interface RoleGuide {
  /** 角色中文名（复用 role.ts ROLE_CN） */
  title: string
  /** 核心职责 3-4 条，新人能看懂的大白话 */
  responsibilities: string[]
  /** 在 11 步流程里负责的步骤文案 */
  flowRange: string
  /** 负责的步骤序号（流程图高亮用） */
  flowStepSeqs: number[]
  /** 暂无待办时的快捷入口（route 必须在 roleMenu 白名单内） */
  quickActions: ReadonlyArray<{ label: string; route: string }>
}

export const ROLE_GUIDE: Record<string, RoleGuide> = {
  PROCUREMENT: {
    title: roleName('PROCUREMENT'),
    responsibilities: ['建立项目', '录入销售合同', '录入采购合同', '下达批次订单'],
    flowRange: '第 1–4 步',
    flowStepSeqs: [1, 2, 3, 4],
    quickActions: [
      { label: '新建项目', route: '/master/projects' },
      { label: '录入采购合同', route: '/master/contracts' },
      { label: '下达批次订单', route: '/master/orders' },
      { label: '维护供应商', route: '/master/suppliers' },
    ],
  },
  DELIVERY: {
    title: roleName('DELIVERY'),
    responsibilities: ['导入设备清单', '推进设备到货', '设备上架', '点亮验收'],
    flowRange: '第 5–8 步',
    flowStepSeqs: [5, 6, 7, 8],
    quickActions: [
      { label: '设备清单', route: '/devices' },
      { label: '验收管理', route: '/acceptances' },
    ],
  },
  FINANCE_STAFF: {
    title: roleName('FINANCE_STAFF'),
    responsibilities: ['金租放款', '按台计费', '盈利测算', '发票对账'],
    flowRange: '第 9–11 步',
    flowStepSeqs: [9, 10, 11],
    quickActions: [
      { label: '记流水', route: '/capital' },
      { label: '记采购订单', route: '/master/orders' },
      { label: '按台计费', route: '/billing' },
      { label: '金租流程', route: '/leasing' },
      { label: '发票对账', route: '/invoices' },
    ],
  },
}

/**
 * 是否看原财务首页。
 * admin / 财务总监 / 未知或空角色 → 原首页（fail-open，向后兼容旧会话）。
 */
export function seesOriginalDashboard(role: string | null | undefined): boolean {
  if (!role) return true
  return role === 'ADMIN' || role === 'FINANCE_DIRECTOR'
}

/** 取角色引导；无引导的角色（admin / 总监 / 未知）返回 null */
export function getRoleGuide(role: string | null | undefined): RoleGuide | null {
  if (!role) return null
  return ROLE_GUIDE[role] ?? null
}

/** 职责横幅关闭状态（localStorage：用户关掉后不再强提醒，新人可手动召回） */
export function readHideGuideBanner(): boolean {
  try {
    return localStorage.getItem('siegpu:hideGuideBanner') === '1'
  } catch {
    return false
  }
}
export function writeHideGuideBanner(hide: boolean): void {
  try {
    localStorage.setItem('siegpu:hideGuideBanner', hide ? '1' : '0')
  } catch {
    /* 隐私模式等写入失败，忽略 */
  }
}
