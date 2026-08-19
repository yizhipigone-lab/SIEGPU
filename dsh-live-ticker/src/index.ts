/**
 * dsh-live-ticker host 面：
 * 注册同源 JSON 路由，代理东财数据（浏览器不直连跨域）：
 *   /live-ticker/news   东财新闻列表（30s 缓存）
 *   /live-ticker/quotes 东财指数行情（3s 缓存）
 * handler 为 Node http 风格 (req, res) -> void | Promise<void>，自行写响应。
 */

import type { Context } from '@deepseek-ai/cordis'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { NewsCache, fetchEfinanceNews } from './news.ts'
import { fetchQuotesFromEastMoney } from './quotes.ts'

export const name = 'dsh-live-ticker'
export const inject = ['webServer']

const NEWS_CACHE_TTL_MS = 30_000
const QUOTES_CACHE_TTL_MS = 3_000
const NEWS_ROUTE = '/live-ticker/news'
const QUOTES_ROUTE = '/live-ticker/quotes'

export function apply(ctx: Context) {
  const newsCache = new NewsCache(NEWS_CACHE_TTL_MS)
  let quotesCache: { quotes: ReturnType<typeof fetchQuotesFromEastMoney> extends Promise<infer T> ? T : never; fetchedAt: number } | null = null
  let registered = false

  function sendJson(res: ServerResponse, status: number, body: unknown): void {
    const text = JSON.stringify(body)
    res.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    })
    res.end(text)
  }

  function tryRegister(webServer: unknown) {
    if (registered) return
    const server = webServer as {
      register: (def: { kind: string; path: string; handler: (req: IncomingMessage, res: ServerResponse) => void | Promise<void> }) => () => void
    }
    if (server === undefined || typeof server.register !== 'function') return

    server.register({
      kind: 'prefix',
      path: NEWS_ROUTE,
      handler: async (_req, res) => {
        const cached = newsCache.get()
        if (cached) {
          sendJson(res, 200, { ok: true, ...cached })
          return
        }
        try {
          const snapshot = await fetchEfinanceNews()
          newsCache.set(snapshot)
          sendJson(res, 200, { ok: true, ...snapshot })
        } catch (err) {
          const last = newsCache.last()
          sendJson(res, 200, {
            ok: false,
            stale: true,
            items: last?.items ?? [],
            error: err instanceof Error ? err.message : String(err),
          })
        }
      },
    })

    server.register({
      kind: 'prefix',
      path: QUOTES_ROUTE,
      handler: async (_req, res) => {
        const cached = quotesCache
        if (cached && Date.now() - cached.fetchedAt < QUOTES_CACHE_TTL_MS) {
          sendJson(res, 200, { ok: true, quotes: cached.quotes, fetchedAt: cached.fetchedAt })
          return
        }
        try {
          const quotes = await fetchQuotesFromEastMoney()
          quotesCache = { quotes, fetchedAt: Date.now() }
          sendJson(res, 200, { ok: true, quotes, fetchedAt: quotesCache.fetchedAt })
        } catch (err) {
          sendJson(res, 200, {
            ok: false,
            stale: quotesCache !== null,
            quotes: quotesCache?.quotes ?? [],
            error: err instanceof Error ? err.message : String(err),
          })
        }
      },
    })

    registered = true
  }

  const existing = ctx.reflect.get('webServer', false)
  tryRegister(existing)
  ctx.on('internal/service', (sName: string, value: unknown) => {
    if (sName === 'webServer') tryRegister(value)
  })
}
