/**
 * 指数行情：腾讯 qt.gtimg.cn 批量接口（Node 环境可直连，GBK 编码）。
 * 由 host 端代理抓取（同源 /live-ticker/quotes），浏览器不直连跨域。
 * 4 个指数：上证 sh000001 / 创业板 sz399006 / 科创50 sh000688 / 中证A500 sh000510。
 * 注意：中证A500 在腾讯是 sh000510（东财用 1.000510，不要混用）。
 */

export interface Quote {
  name: string
  price: number
  changePct: number
}

/** 腾讯指数代码（q= 参数）。 */
export const INDEX_CODES = ['sh000001', 'sz399006', 'sh000688', 'sh000510'] as const

export const QUOTES_URL = `https://qt.gtimg.cn/q=${INDEX_CODES.join(',')}`

/** 解析腾讯 qt.gtimg.cn 响应（v_xxx="~分隔字段"），按 INDEX_CODES 顺序返回。 */
export function parseTencentQuotes(text: string): Quote[] {
  const quotes: Quote[] = []
  for (const line of text.split(';')) {
    const m = /v_\w+="([^"]*)"/.exec(line)
    if (!m) continue
    const f = m[1].split('~')
    const name = f[1]?.trim()
    const price = toNum(f[3])
    const changePct = toNum(f[32])
    if (!name || price === null || changePct === null) continue
    quotes.push({ name, price, changePct })
  }
  return quotes
}

/** 转数字：空/纯空白/非数字字符串与 undefined 返回 null（避免 Number('')===0 误判）。 */
function toNum(v: unknown): number | null {
  if (typeof v !== 'string') return null
  const s = v.trim()
  if (s === '') return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/** host 端抓取腾讯指数并解析（GBK 解码）；失败抛错由调用方兜底。 */
export async function fetchQuotesFromTencent(fetchImpl: typeof fetch = fetch): Promise<Quote[]> {
  const res = await fetchImpl(QUOTES_URL)
  if (!res.ok) throw new Error(`tencent quotes HTTP ${res.status}`)
  const buf = await res.arrayBuffer()
  return parseTencentQuotes(new TextDecoder('gbk').decode(buf))
}
