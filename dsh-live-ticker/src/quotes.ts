/**
 * 指数行情：东财 push2 ulist 批量接口。浏览器直连（CORS `*`）。
 * 注意：中证A500 必须用 1.000510（0.000510 是深市个股"新金路"）。
 */

export interface Quote {
  name: string
  price: number
  changePct: number
}

export const INDEX_SECIDS = ['1.000001', '0.399006', '1.000688', '1.000510'] as const

export const QUOTES_URL =
  'https://push2.eastmoney.com/api/qt/ulist.np/get' +
  `?fltt=2&secids=${INDEX_SECIDS.join(',')}&fields=f2,f3,f12,f14`

/** 东财返回的价格/涨跌幅可能是数字或带千分位的字符串（fltt=2 下一般为数字）。 */
function toNumber(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string') {
    const n = Number(v.replace(/,/g, ''))
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** 解析东财 ulist.np/get 响应：按 diff 数组顺序返回，缺 name/price/changePct 的条目丢弃。 */
export function parsePush2Quotes(json: unknown): Quote[] {
  const diff = (json as { data?: { diff?: unknown[] } })?.data?.diff
  if (!Array.isArray(diff)) return []
  const quotes: Quote[] = []
  for (const row of diff) {
    const r = row as Record<string, unknown>
    if (typeof r.f14 !== 'string' || !r.f14.trim()) continue
    const price = toNumber(r.f2)
    const changePct = toNumber(r.f3)
    if (price === null || changePct === null) continue
    quotes.push({ name: r.f14.trim(), price, changePct })
  }
  return quotes
}
