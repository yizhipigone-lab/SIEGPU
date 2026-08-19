/**
 * dsh-live-ticker host 面：
 * 注册同源 JSON 路由 /live-ticker/news，代理东财新闻列表（30s 缓存）。
 * handler 为 Node http 风格 (req, res) -> void | Promise<void>，自行写响应。
 */

import type { Context } from '@deepseek-ai/cordis'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { NewsCache, fetchEfinanceNews } from './news.ts'

export const name = 'dsh-live-ticker'
export const inject = ['webServer']

const CACHE_TTL_MS = 30_000
const ROUTE = '/live-ticker/news'

export function apply(ctx: Context) {
  const cache = new NewsCache(CACHE_TTL_MS)
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
      path: ROUTE,
      handler: async (_req, res) => {
        const cached = cache.get()
        if (cached) {
          sendJson(res, 200, { ok: true, ...cached })
          return
        }
        try {
          const snapshot = await fetchEfinanceNews()
          cache.set(snapshot)
          sendJson(res, 200, { ok: true, ...snapshot })
        } catch (err) {
          const last = cache.last()
          sendJson(res, 200, {
            ok: false,
            stale: true,
            items: last?.items ?? [],
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
