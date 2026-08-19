/**
 * 东方财富新闻抓取与 30s 缓存。纯 Node，无第三方依赖（Node 18+ 原生 fetch）。
 * 仅导出纯函数与缓存类，便于 node:test 单测；真实网络抓取在 Task 3 的路由里。
 */

export interface NewsItem {
  title: string
  /** 截断到分钟，如 "2026-08-19 07:50" */
  showTime: string
  url: string
}

export interface NewsSnapshot {
  items: NewsItem[]
  fetchedAt: number
  stale: boolean
}

const NEWS_URL =
  'https://np-listapi.eastmoney.com/comm/web/getNewsByColumns' +
  '?client=web&biz=web_news_col&column=350&order=1&needInteractData=0' +
  '&page_index=1&page_size=10&req_trace=1&fields=code,showTime,title,url'

/** 解析东财 getNewsByColumns 响应：丢弃缺 title、url 或 showTime 的条目，showTime 截断到分钟。 */
export function parseEfinanceNews(json: unknown): NewsItem[] {
  const list = (json as { data?: { list?: unknown[] } })?.data?.list
  if (!Array.isArray(list)) return []
  const items: NewsItem[] = []
  for (const row of list) {
    const r = row as Record<string, unknown>
    if (typeof r.title !== 'string' || !r.title.trim()) continue
    if (typeof r.url !== 'string' || !r.url.trim()) continue
    if (typeof r.showTime !== 'string' || !r.showTime.trim()) continue
    items.push({
      title: r.title.trim(),
      showTime: r.showTime.slice(0, 16),
      url: r.url.trim(),
    })
  }
  return items
}

/** 内存缓存：TTL 内命中；过期视为未命中（stale 快照由调用方自行保留）。 */
export class NewsCache {
  private value: NewsSnapshot | null = null
  private readonly ttlMs: number

  constructor(ttlMs: number) {
    this.ttlMs = ttlMs
  }

  set(snapshot: NewsSnapshot): void {
    this.value = snapshot
  }

  get(): NewsSnapshot | null {
    if (!this.value) return null
    if (Date.now() - this.value.fetchedAt > this.ttlMs) return null
    return this.value
  }

  last(): NewsSnapshot | null {
    return this.value
  }
}

/** 抓取东财新闻并返回快照；失败时 last() 可回退。 */
export async function fetchEfinanceNews(fetchImpl: typeof fetch = fetch): Promise<NewsSnapshot> {
  const res = await fetchImpl(NEWS_URL)
  if (!res.ok) throw new Error(`eastmoney news HTTP ${res.status}`)
  const items = parseEfinanceNews(await res.json())
  return { items, fetchedAt: Date.now(), stale: false }
}
