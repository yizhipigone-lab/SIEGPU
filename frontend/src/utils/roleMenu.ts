/**
 * 角色菜单白名单 —— 侧边栏按角色过滤 + 路由守卫的单一事实源。
 *
 * 依据：OPERATION-GUIDE §4.1 权限矩阵 + §6.2 18 步流程 doer_role + 业务实际。
 * 改这里即可调整某角色可见菜单，无需动 MainLayout / router。
 *
 * 语义：
 *  - ADMIN / FINANCE_DIRECTOR：看全部（总监需全局视野，且保证现有 e2e 用 cfo 不受影响）。
 *  - 其余角色（FINANCE_STAFF / PROCUREMENT / DELIVERY）：仅看白名单内 + 公共菜单。
 *  - role 为空 / 未知：fail-open 看全部（不锁人，向后兼容旧会话 / token 未带 role 的历史浏览器）。
 *  - 用户可在顶栏开「显示全部菜单」逃生口（一人多角的小部门），开关状态读 localStorage。
 */

/** 所有登录角色始终可见的公共路由（不论角色） */
export const PUBLIC_MENU_KEYS: ReadonlySet<string> = new Set([
  '/',              // 首页（看板 + 待办，人人都看）
  '/portfolio',     // 项目总览（组合视角，各角色都需了解项目状态）
  '/sales-orders',  // 销售订单（用户决策：所有人可见）
])

/**
 * 角色 → 专属菜单路由 key 白名单（不含公共菜单，公共菜单见 PUBLIC_MENU_KEYS）。
 * 未列出的角色（ADMIN / FINANCE_DIRECTOR）= 看全部。
 */
export const ROLE_MENU: Record<string, readonly string[]> = {
  // 财务专员：资金 / 发票 / 金租 / 计费 / 客户对账单 / 资产 / 银行 + 客户确认 + 设备（回租出售）+ 项目
  FINANCE_STAFF: [
    '/capital', '/invoices', '/leasing', '/billing', '/customer-statement',
    '/confirmations', '/devices',
    '/master/assets', '/master/banks', '/master/projects', '/master/orders',
    '/ebs', // 二期 W1-2：业财一体化 EBS 出站监控
    '/exchange-rates', // 二期 W5-6：币种与汇率管理
    '/insurance', // 二期 W7-8：保险管理
    '/prepayments', // 二期 W9-10：预付款台账
    '/payments', // 二期 W11-12：付款管控+审批中心
    '/revenue-recognitions', // 三期 §4.2：收入确认
    '/reconciliation-center', // 三期 §4.3：对账中心
  ],
  // 采购对接人（兼商务）：设备 / 项目 / 合同 / 订单 + 主数据维护（供应商/客户/设备型号）
  PROCUREMENT: [
    '/devices',
    '/master/projects', '/master/contracts', '/master/orders',
    '/master/suppliers', '/master/customers', '/master/equipment',
  ],
  // 项目交付：设备推进 / 验收 / 客户确认 + 项目 + 设备型号 + 订单（看采购进度）
  DELIVERY: [
    '/devices', '/acceptances', '/confirmations',
    '/master/projects', '/master/equipment', '/master/orders',
  ],
}

/** 读取「显示全部菜单」逃生口开关（localStorage，顶栏按钮切换） */
export function readShowAllMenus(): boolean {
  try {
    return localStorage.getItem('siegpu:showAllMenus') === '1'
  } catch {
    return false
  }
}

/** 写「显示全部菜单」开关 */
export function writeShowAllMenus(on: boolean): void {
  try {
    localStorage.setItem('siegpu:showAllMenus', on ? '1' : '0')
  } catch {
    /* 忽略隐私模式等写入失败 */
  }
}

/**
 * 是否对该角色显示全部菜单。
 * true 的四种情况：用户开了逃生口 / role 为空或未知（fail-open）/ 管理员 / 财务总监。
 */
export function roleSeesAll(role: string | null | undefined, showAll: boolean): boolean {
  if (showAll) return true
  if (!role) return true
  return role === 'ADMIN' || role === 'FINANCE_DIRECTOR'
}

/**
 * 某路由 key 是否对该角色可见。
 * 用于侧边栏过滤；路由守卫也复用此函数（路径即 key）。
 */
export function isMenuAllowed(
  role: string | null | undefined,
  key: string,
  showAll: boolean,
): boolean {
  if (roleSeesAll(role, showAll)) return true
  if (PUBLIC_MENU_KEYS.has(key)) return true
  const allowed = ROLE_MENU[role ?? '']
  return allowed ? allowed.includes(key) : true // 未知角色 fail-open
}
