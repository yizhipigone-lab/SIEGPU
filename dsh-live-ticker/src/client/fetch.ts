/**
 * client 数据层：指数与新闻均走同源 host 路由（浏览器不直连跨域）。
 *   /live-ticker/quotes  指数（host 代理东财 push2，3s 缓存）
 *   /live-ticker/news    新闻（host 代理东财新闻，30s 缓存）
 * 纯浏览器代码，不 import host 模块。
 */

import type { Quote } from '../quotes.ts'
import type { NewsSnapshot } from '../news.ts'

export interface QuotesResult {
  quotes: Quote[]
  fetchedAt: number
  ok: boolean
}

export async function fetchQuotes(signal?: AbortSignal): Promise<QuotesResult> {
  try {
    const res = await fetch('/live-ticker/quotes', { signal })
    if (!res.ok) return { quotes: [], fetchedAt: Date.now(), ok: false }
    const body = await res.json() as { ok: boolean; quotes: Quote[]; fetchedAt: number }
    if (!body.ok) return { quotes: body.quotes ?? [], fetchedAt: Date.now(), ok: false }
    return { quotes: body.quotes, fetchedAt: body.fetchedAt ?? Date.now(), ok: true }
  } catch {
    return { quotes: [], fetchedAt: Date.now(), ok: false }
  }
}

export interface NewsResult {
  snapshot: NewsSnapshot | null
  ok: boolean
  error?: string
}

/**
 * 拉取新闻。host 在抓取失败时会返回 ok:false 但携带上次成功快照（stale=true），
 * 这里把该快照透出（ok 仍为 false），让 UI 能显示"上次数据"。
 */
export async function fetchNews(signal?: AbortSignal): Promise<NewsResult> {
  try {
    const res = await fetch('/live-ticker/news', { signal })
    if (!res.ok) return { snapshot: null, ok: false, error: `HTTP ${res.status}` }
    const body = await res.json() as { ok: boolean; items: unknown[]; fetchedAt: number; stale: boolean; error?: string }
    if (!body.ok) {
      return {
        snapshot: Array.isArray(body.items) && body.items.length > 0
          ? { items: body.items as never, fetchedAt: body.fetchedAt ?? 0, stale: true }
          : null,
        ok: false,
        error: body.error,
      }
    }
    return {
      snapshot: { items: body.items as never, fetchedAt: body.fetchedAt, stale: body.stale },
      ok: true,
    }
  } catch (e) {
    return { snapshot: null, ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}
