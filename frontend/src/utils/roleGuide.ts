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
import { computed, type ComputedRef } from 'vue'
import { roleName } from './role'
import { useMetaStore } from '../stores/meta'

/**
 * 流程步骤元数据 —— 流程图节点 + 路由 + 一句话说明的单一事实源。
 *
 * route 必须落在对应角色 roleMenu.ts 白名单内，否则点击后会被路由守卫拦回首页；
 * FlowMap 会用 isMenuAllowed 把无权节点置灰（显示「由 XX 负责」），不会放人过去。
 */
export interface FlowStep {
  seq: number
  name: string
  /** 点节点跳转的业务页面 */
  route: string
  /** 悬停/展开的「这一步做什么」一句话 */
  desc: string
  /** 负责角色 key（用于置灰提示与属地着色） */
  role: 'PROCUREMENT' | 'DELIVERY' | 'FINANCE_STAFF'
  /**
   * 单据 vs 动作 —— 新手最容易混淆的轴：
   *  - doc    = 建一次存下来的单据（项目/合同/订单），新手要「填表」
   *  - action = 项目生命周期里发生的事（导入/到货/放款/计费），新手要「推进度」
   * 泳道图据此给两种节点不同图标与底色。
   */
  kind: 'doc' | 'action'
  /**
   * 标准 18 步模板里对应的步骤名（设备模板 11 步是精简主链路，标准模板更细分）。
   * 用于：① 术语对齐提示 ② 首页待办锚点按步骤名反查。
   */
  aliases?: string[]
}

/** 11 步流程静态骨架（与后端 _device_flow_steps 同源，名称逐字对齐）。
 * desc 是本地兜底；运行时以 meta store 的 STEP_HINTS（后端真源）覆盖。 */
const FLOW_STEPS_BASE: readonly FlowStep[] = [
  { seq: 1, name: '项目建立', route: '/master/projects', kind: 'doc', role: 'PROCUREMENT', desc: '录入项目并选择流程模板，系统自动生成向导' },
  { seq: 2, name: '销售合同', route: '/master/contracts', kind: 'doc', role: 'PROCUREMENT', desc: '录入与客户的销售合同（收入侧）' },
  { seq: 3, name: '采购合同', route: '/master/contracts', kind: 'doc', role: 'PROCUREMENT', desc: '录入与设备厂商的采购合同（支出侧）' },
  { seq: 4, name: '批次订单', route: '/orders?tab=purchase', kind: 'doc', role: 'PROCUREMENT', desc: '按采购合同下达批次订单', aliases: ['销售订单', '采购订单'] },
  { seq: 5, name: '设备导入', route: '/devices', kind: 'action', role: 'DELIVERY', desc: '批量导入设备清单并逐台建档' },
  { seq: 6, name: '设备到货', route: '/devices', kind: 'action', role: 'DELIVERY', desc: '推进设备到货节点' },
  { seq: 7, name: '设备上架', route: '/devices', kind: 'action', role: 'DELIVERY', desc: '设备上架入库，准备点亮' },
  { seq: 8, name: '点亮验收', route: '/acceptances', kind: 'action', role: 'DELIVERY', desc: '设备点亮上线并完成验收，自动转资产', aliases: ['采购验收', '销售验收', '点亮'] },
  { seq: 9, name: '金租放款', route: '/leasing', kind: 'action', role: 'FINANCE_STAFF', desc: '金租公司放款到账，自动生成还款计划', aliases: ['金租申请', '金租放款+置换'] },
  { seq: 10, name: '按台计费', route: '/billing', kind: 'action', role: 'FINANCE_STAFF', desc: '按设备台数与点亮周期生成计费单', aliases: ['计费'] },
  { seq: 11, name: '盈利测算', route: '/profit', kind: 'action', role: 'FINANCE_STAFF', desc: '基于真实参数测算项目盈利并留存场景', aliases: ['客户确认', '开票+回款+核销'] },
]

/** 11 步流程（computed）：desc 以 meta store 的 STEP_HINTS（后端真源）为准，失败回退本地骨架。 */
export const FLOW_STEPS: ComputedRef<readonly FlowStep[]> = computed(() => {
  let hints: Record<string, string> = {}
  try {
    hints = useMetaStore().stepHints
  } catch {
    /* pinia 未激活（如纯函数单测场景）：用本地兜底 */
  }
  return FLOW_STEPS_BASE.map((s) => ({ ...s, desc: hints[s.name] ?? s.desc }))
})

/** 泳道：把 11 步按角色分成三段接力，直观回答「谁做什么、在哪交接、我负责哪段」。 */
export interface FlowLane {
  role: 'PROCUREMENT' | 'DELIVERY' | 'FINANCE_STAFF'
  /** 泳道副标签（职责一句话） */
  subtitle: string
  steps: FlowStep[]
}

export const FLOW_LANES: ComputedRef<readonly FlowLane[]> = computed(() => [
  { role: 'PROCUREMENT', subtitle: '建单据 · 第 1–4 步', steps: FLOW_STEPS.value.filter((s) => s.role === 'PROCUREMENT') },
  { role: 'DELIVERY', subtitle: '推落地 · 第 5–8 步', steps: FLOW_STEPS.value.filter((s) => s.role === 'DELIVERY') },
  { role: 'FINANCE_STAFF', subtitle: '收尾 · 第 9–11 步', steps: FLOW_STEPS.value.filter((s) => s.role === 'FINANCE_STAFF') },
])

/** 按步骤名（或标准模板别名）反查流程步骤 —— 供首页待办锚点用。 */
export function flowStepByTaskName(name: string): FlowStep | undefined {
  return FLOW_STEPS.value.find((s) => s.name === name || (s.aliases?.includes(name) ?? false))
}

/**
 * 页面级定位提示（P2）—— 每个业务页页头一句「这是流程第几步 · 谁负责 · 依赖上一步」。
 * 解决新手点进「验收/回款/金租」等页面后迷失的问题。
 * 首页与工作台不挂提示（各自已有完整上下文）。
 */
export const PAGE_HINTS: Readonly<Record<string, string>> = {
  '/master/projects': '流程第 1 步 · 项目建立 · 由采购对接人负责 · 这是整条链路的起点',
  '/master/contracts': '流程第 2–3 步 · 销售合同 / 采购合同 · 由采购对接人负责 · 依赖：项目已建立',
  '/orders': '流程第 4 步 · 订单（采购订单 / 销售订单 双 Tab）· 由采购对接人负责 · 依赖：合同已录入',
  '/master/orders': '流程第 4 步 · 批次订单（标准模板拆为销售订单+采购订单）· 由采购对接人负责 · 依赖：合同已录入',
  '/sales-orders': '标准模板第 4 步 · 销售订单 · 由采购对接人负责 · 依赖：销售合同',
  '/devices': '流程第 5–7 步 · 设备导入 / 到货 / 上架 · 由项目交付负责人负责 · 依赖：批次订单',
  '/acceptances': '流程第 8 步 · 点亮验收（标准模板含采购验收/销售验收/点亮）· 由项目交付负责人负责 · 依赖：设备上架',
  '/leasing': '流程第 9 步 · 金租放款（标准模板含金租申请/放款+置换）· 由财务负责 · 依赖：点亮验收',
  '/billing': '流程第 10 步 · 按台计费（标准模板叫计费）· 由财务专员负责 · 依赖：金租放款',
  '/profit': '流程第 11 步 · 盈利测算（标准模板含客户确认/开票+回款+核销）· 由财务专员负责 · 依赖：按台计费',
  '/capital': '资金线 · 资金池流水（标准模板第 6–8 步入金/预付款在此登记）· 由财务专员负责',
  '/invoices': '财务核算 · 发票/对账（标准模板第 17 步「开票+回款+核销」在此办理）· 由财务专员负责',
  '/customer-statement': '销售线 · 客户对账单（合同额→计费→开票→回款 三流核对）· 由财务专员负责',
  '/confirmations': '销售线 · 客户确认（标准模板第 16 步）· 由财务专员负责 · 依赖：计费',
  '/prepayments': '资金线 · 预付款台账 · 设备预付款余额聚合视图 · 由财务专员负责',
}

/** 取页面定位提示；无提示（首页/工作台/无关页）返回 null */
export function pageHint(path: string): string | null {
  return PAGE_HINTS[path] ?? null
}

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
      { label: '下达批次订单', route: '/orders?tab=purchase' },
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
      { label: '记采购订单', route: '/orders?tab=purchase' },
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
