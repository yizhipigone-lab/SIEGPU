/** 金额/状态格式化工具（单一来源，供表格与卡片复用）。 */

export function money(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 时间戳 → YYYY-MM-DD（本地时区）。naive-ui NDatePicker 的 value 只接受时间戳，提交前需转字符串。 */
export function tsToYmd(ts: number | null | undefined): string {
  if (ts === null || ts === undefined) return ''
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** YYYY-MM-DD → 时间戳（供 NDatePicker :value 绑定）；空值/非法值返回 null。 */
export function ymdToTs(s: string | null | undefined): number | null {
  if (!s) return null
  const ts = new Date(`${s}T00:00:00`).getTime()
  return Number.isNaN(ts) ? null : ts
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
