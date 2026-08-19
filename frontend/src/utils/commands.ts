/**
 * 命令面板动作注册表 —— Ctrl+K 搜索的单一事实源。
 *
 * 每条 = 一个可直达的页面动作：title 显示名，route 跳转目标，keywords 搜索别名
 * （中文同义词/拼音首字母/英文，全部小写比较），group 与侧边栏流程域分组同名。
 *
 * route 必须存在于 router/index.ts；无权项由 CommandPalette 用 isMenuAllowed 置灰，
 * 不在此过滤（让新手看得到「这事归谁管」）。
 */
export interface CommandItem {
  title: string
  route: string
  keywords: string[]
  group: string
}

export const COMMANDS: readonly CommandItem[] = [
  // 经营总览
  { title: '首页', route: '/', keywords: ['首页', '看板', '待办', 'home', 'dashboard', 'sy'], group: '经营总览' },
  { title: '项目总览', route: '/portfolio', keywords: ['项目总览', '组合', '停滞', 'portfolio', 'xmzl'], group: '经营总览' },
  { title: '项目对比', route: '/comparison', keywords: ['项目对比', 'irr', 'npv', '对比', 'xmdb'], group: '经营总览' },
  { title: '利润测算', route: '/profit', keywords: ['利润测算', '盈利', '测算', 'profit', 'lrcs'], group: '经营总览' },
  // 业务对象
  { title: '项目', route: '/master/projects', keywords: ['项目', '建项目', '新建项目', 'project', 'xm'], group: '业务对象' },
  { title: '合同', route: '/master/contracts', keywords: ['合同', '销售合同', '采购合同', 'contract', 'ht'], group: '业务对象' },
  { title: '订单', route: '/orders?tab=purchase', keywords: ['订单', '采购订单', '批次订单', '下订单', 'order', 'dd'], group: '业务对象' },
  { title: '资产', route: '/master/assets', keywords: ['资产', '折旧', 'asset', 'zc'], group: '业务对象' },
  // 采购交付线
  { title: '设备清单', route: '/devices', keywords: ['设备', '点亮', '上架', '到货', '导入', 'gpu', 'device', 'sb'], group: '采购交付线' },
  { title: '验收管理', route: '/acceptances', keywords: ['验收', '采购验收', '销售验收', 'acceptance', 'ys'], group: '采购交付线' },
  // 资金线
  { title: '资金池', route: '/capital', keywords: ['资金池', '流水', '入金', '出金', '调配', '注资', '红冲', 'capital', 'zjc'], group: '资金线' },
  { title: '预付款', route: '/prepayments', keywords: ['预付款', '预付', 'prepayment', 'yfk'], group: '资金线' },
  { title: '付款管控', route: '/payments', keywords: ['付款', '审批', 'payment', 'fk'], group: '资金线' },
  { title: '金租流程', route: '/leasing', keywords: ['金租', '放款', '还款', '租赁', '置换', 'leasing', 'jz', 'fk'], group: '资金线' },
  // 销售线
  { title: '销售订单', route: '/orders?tab=sales', keywords: ['销售订单', 'sales', 'xsdd'], group: '业务对象' },
  { title: '计费管理', route: '/billing', keywords: ['计费', '账单', '按台计费', 'billing', 'jf'], group: '销售线' },
  { title: '客户确认', route: '/confirmations', keywords: ['客户确认', '争议', 'confirmation', 'khqr'], group: '销售线' },
  { title: '客户对账单', route: '/customer-statement', keywords: ['对账单', '客户对账', '回款', 'statement', 'dzd', 'hk'], group: '销售线' },
  // 财务核算
  { title: '发票/对账', route: '/invoices', keywords: ['发票', '开票', 'ocr', '红冲', '核销', '三流对账', 'invoice', 'fp', 'kp', 'hx'], group: '财务核算' },
  { title: '收入确认', route: '/revenue-recognitions', keywords: ['收入确认', '收入', 'revenue', 'srqr'], group: '财务核算' },
  { title: '对账中心', route: '/reconciliation-center', keywords: ['对账', '对账中心', 'reconcile', 'dz'], group: '财务核算' },
  { title: '退货管理', route: '/returns', keywords: ['退货', 'return', 'th'], group: '财务核算' },
  { title: '币种汇率', route: '/exchange-rates', keywords: ['汇率', '币种', 'currency', 'rate', 'hl'], group: '财务核算' },
  { title: '保险管理', route: '/insurance', keywords: ['保险', 'insurance', 'bx'], group: '财务核算' },
  { title: 'EBS 监控', route: '/ebs', keywords: ['ebs', '同步', '出站', '监控', 'tb'], group: '财务核算' },
  // 主数据
  { title: '供应商', route: '/master/suppliers', keywords: ['供应商', '金租公司', 'supplier', 'gys'], group: '主数据' },
  { title: '客户', route: '/master/customers', keywords: ['客户', '租户', 'customer', 'kh'], group: '主数据' },
  { title: '设备型号', route: '/master/equipment', keywords: ['设备型号', '型号', '5090', 'equipment', 'sbxh'], group: '主数据' },
  { title: '银行', route: '/master/banks', keywords: ['银行', 'bank', 'yh'], group: '主数据' },
]
