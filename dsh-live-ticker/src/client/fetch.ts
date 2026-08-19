/**
 * client 数据层：指数直连东财 push2（CORS *），新闻走同源 /live-ticker/news。
 * 纯浏览器代码，不 import host 模块。
 */

import type { Quote } from '../quotes.ts'
import { QUOTES_URL, parsePush2Quotes } from '../quotes.ts'
import type { NewsSnapshot } from '../news.ts'

export interface QuotesResult {
  quotes: Quote[]
  fetchedAt: number
  ok: boolean
}

export async function fetchQuotes(signal?: AbortSignal): Promise<QuotesResult> {
  try {
    const res = await fetch(QUOTES_URL, { signal })
    if (!res.ok) return { quotes: [], fetchedAt: Date.now(), ok: false }
    return { quotes: parsePush2Quotes(await res.json()), fetchedAt: Date.now(), ok: true }
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
