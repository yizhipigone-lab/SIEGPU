/** 金额/状态格式化工具（单一来源，供表格与卡片复用）。 */

export function money(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 状态/枚举值 → NTag 类型（语义色）。 */
export function statusTagType(v: string): string {
  const m: Record<string, string> = {
    // 成功类
    '已完成': 'success', '已签': 'success', '已放款': 'success', '已收款': 'success',
    '已付款': 'success', '已还': 'success', '已到货': 'success', '已点亮': 'success',
    '折旧中': 'info', '已归还': 'success', '已开': 'info',
    // 进行/信息类
    '进行中': 'info', '执行中': 'info', '已批': 'info',
    // 默认/待办
    '部分到货': 'warning', '待还': 'default', '待开': 'default', '草稿': 'default',
    '未开始': 'default', '已下单': 'default', '进行中 ': 'info',
    // 异常
    '已红冲': 'error', '逾期': 'error', '已拒绝': 'error', '卡住': 'error', '已终止': 'error', '暂停': 'warning',
    // 方向/类型
    IN: 'success', OUT: 'warning', RECEIVABLE: 'info', PAYABLE: 'warning',
    SALES: 'info', PURCHASE: 'warning',
    '资金供应商': 'warning', '设备供应商': 'info', '其他': 'default',
    '大卡': 'info', '小卡': 'warning', '组网设备': 'success',
  }
  return m[v] ?? 'default'
}
