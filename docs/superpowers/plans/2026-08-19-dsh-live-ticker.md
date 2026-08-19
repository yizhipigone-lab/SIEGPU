# dsh-live-ticker 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DSH Web profile 对话框底部（输入框卡片下方）添加两个可折叠行：4 个指数实时行情（浏览器直连东财 push2）+ 东财财经新闻横向滚动（host 代理同源路由）。

**Architecture:** 单 bundle 插件，host + client 双面。host 面（Node，`src/index.ts`，tsx 加载）用 `webServer.register` 注册同源 JSON 路由 `/live-ticker/news` 代理东财新闻（30s 缓存，无 CORS 问题的根源解法）；client 面（浏览器 React，构建为 `window.__ModuleLoader__` 格式）注册 `conversation.composer.dock` 槽位渲染两个 `<details open>` 行，指数直连东财 push2（CORS `*`），新闻 `fetch('/live-ticker/news')` 同源拉取。

**Tech Stack:** TypeScript、React 18（client）、node:test（host 测试）、esbuild（client 构建）、@deepseek-ai/cordis + @deepseek-ai/dsh-tools（host API）、@deepseek-ai/dsh-client-ui-slots + @deepseek-ai/dsh-client-connection（client API）。

**与设计文档的实现决策修正（§6.2 已预留降级路径）：** host 侧不用 Remote `live-ticker/fetch-news`，改用 `webServer.register` 注册同源路由 `/live-ticker/news`——genui 已实测该模式（`webServer.register({kind:'prefix', path, handler})`），client 直接 `fetch('/live-ticker/news')` 同源请求，无 CORS、无需连接层协议，比 Remote 更简单确定。

**文件结构：**

```
E:\1target\SIEGPU\dsh-live-ticker\
├── package.json              # name/main/scripts；dsh.bundle.patch + dsh.client.inject
├── cordis.patch.yml          # insert: - id: live-ticker (host 行) + client 注入声明
├── src/
│   ├── index.ts              # host apply：注册 /live-ticker/news 路由
│   ├── news.ts               # 东财新闻抓取 + 解析 + 30s 缓存（可单测）
│   ├── quotes.ts             # 指数 secid 常量 + push2 响应解析（可单测）
│   └── client/
│       ├── index.tsx         # client apply：slots.inject('conversation.composer.dock', ...)
│       ├── TickerBar.tsx     # 两个可折叠行组件
│       └── fetch.ts          # 东财 push2 直连 + /live-ticker/news 拉取
├── scripts/
│   └── build-client.mjs      # esbuild 构建 client.js（banner 包装 __ModuleLoader__）
├── lib/client.js             # 构建产物（提交）
├── tests/
│   ├── news.test.mjs         # node:test：解析 + 缓存
│   └── quotes.test.mjs       # node:test：push2 响应解析
└── README.md
```

---

## Task 1: 插件骨架（package.json + cordis.patch.yml）

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\package.json`
- Create: `E:\1target\SIEGPU\dsh-live-ticker\cordis.patch.yml`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "dsh-live-ticker",
  "version": "0.1.0",
  "description": "DSH plugin: collapsible live index quotes + scrolling finance news under the composer (conversation.composer.dock).",
  "type": "module",
  "main": "src/index.ts",
  "files": ["src", "lib", "scripts", "cordis.patch.yml", "README.md"],
  "scripts": {
    "build:client": "node scripts/build-client.mjs",
    "test": "node --test tests/"
  },
  "dependencies": {
    "@deepseek-ai/cordis": "^4.0.1",
    "@deepseek-ai/dsh-tools": "^0.1.0-rc.6"
  },
  "peerDependencies": {
    "@deepseek-ai/cordis": "*",
    "@deepseek-ai/dsh-tools": "*",
    "@deepseek-ai/dsh-client-connection": "^0.1.0-rc.6",
    "@deepseek-ai/dsh-client-ui-slots": "^0.1.0-rc.6"
  },
  "peerDependenciesMeta": {
    "@deepseek-ai/dsh-client-connection": { "optional": true },
    "@deepseek-ai/dsh-client-ui-slots": { "optional": true }
  },
  "keywords": ["dsh", "dsh-plugin", "deepseek-harness", "finance", "quotes", "ticker"],
  "license": "MIT",
  "dsh": {
    "bundle": {
      "patch": "./cordis.patch.yml"
    },
    "client": {
      "platform": "web",
      "inject": [
        "@deepseek-ai/dsh-client-connection",
        "@deepseek-ai/dsh-client-ui-slots"
      ]
    }
  }
}
```

- [ ] **Step 2: 创建 cordis.patch.yml**

```yaml
- insert:
    - id: live-ticker
      name: dsh-live-ticker
```

- [ ] **Step 3: 校验 JSON/YAML 合法**

Run: `node -e "JSON.parse(require('fs').readFileSync('E:/1target/SIEGPU/dsh-live-ticker/package.json','utf8')); console.log('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/package.json dsh-live-ticker/cordis.patch.yml
git -C E:/1target/SIEGPU commit -m "feat(dsh-live-ticker): 插件骨架 package.json + patch"
```

---

## Task 2: host 新闻抓取与缓存（src/news.ts）

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\src\news.ts`
- Test: `E:\1target\SIEGPU\dsh-live-ticker\tests\news.test.mjs`

- [ ] **Step 1: 写失败测试**

Create `tests/news.test.mjs`:

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { parseEfinanceNews, NewsCache } from '../src/news.ts'

test('parseEfinanceNews 提取标题/时间/链接', () => {
  const json = {
    data: {
      list: [
        { title: '标题一', showTime: '2026-08-19 07:50:32', url: 'http://eastmoney.com/a.html' },
        { title: '标题二', showTime: '2026-08-19 07:40:45', url: 'http://eastmoney.com/b.html' },
      ],
    },
  }
  const items = parseEfinanceNews(json)
  assert.equal(items.length, 2)
  assert.deepEqual(items[0], {
    title: '标题一',
    showTime: '2026-08-19 07:50',
    url: 'http://eastmoney.com/a.html',
  })
})

test('parseEfinanceNews 容错：缺字段条目被丢弃', () => {
  const json = {
    data: { list: [
      { title: '有标题', url: 'http://x/1' },
      { showTime: '2026-08-19 00:00', url: 'http://x/2' },
      { title: '全', showTime: '2026-08-19 00:01', url: 'http://x/3' },
    ] },
  }
  const items = parseEfinanceNews(json)
  assert.equal(items.length, 1)
  assert.equal(items[0].title, '全')
})

test('NewsCache 命中/过期/失败回退', () => {
  const cache = new NewsCache(30_000)
  assert.equal(cache.get(), null)
  const snapshot = { items: [], fetchedAt: Date.now(), stale: false }
  cache.set(snapshot)
  assert.equal(cache.get(), snapshot)
  // 过期
  const old = new NewsCache(30_000)
  old.set({ items: [], fetchedAt: Date.now() - 60_000, stale: false })
  assert.equal(old.get(), null)
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd E:/1target/SIEGPU/dsh-live-ticker && node --test tests/news.test.mjs`
Expected: FAIL（`Cannot find module '../src/news.ts'`）

- [ ] **Step 3: 实现 src/news.ts**

```ts
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

/** 解析东财 getNewsByColumns 响应：丢弃缺 title 或缺 url 的条目，showTime 截断到分钟。 */
export function parseEfinanceNews(json: unknown): NewsItem[] {
  const list = (json as { data?: { list?: unknown[] } })?.data?.list
  if (!Array.isArray(list)) return []
  const items: NewsItem[] = []
  for (const row of list) {
    const r = row as Record<string, unknown>
    if (typeof r.title !== 'string' || !r.title.trim()) continue
    if (typeof r.url !== 'string' || !r.url.trim()) continue
    items.push({
      title: r.title.trim(),
      showTime: typeof r.showTime === 'string' ? r.showTime.slice(0, 16) : '',
      url: r.url.trim(),
    })
  }
  return items
}

/** 内存缓存：TTL 内命中；过期视为未命中（stale 快照由调用方自行保留）。 */
export class NewsCache {
  private value: NewsSnapshot | null = null
  constructor(private readonly ttlMs: number) {}

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
```

- [ ] **Step 4: 运行确认通过**

Run: `cd E:/1target/SIEGPU/dsh-live-ticker && node --test tests/news.test.mjs`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/src/news.ts dsh-live-ticker/tests/news.test.mjs
git -C E:/1target/SIEGPU commit -m "feat(dsh-live-ticker): host 新闻抓取 + 解析 + 30s 缓存（含单测）"
```

---

## Task 3: 指数 secid 与响应解析（src/quotes.ts）

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\src\quotes.ts`
- Test: `E:\1target\SIEGPU\dsh-live-ticker\tests\quotes.test.mjs`

- [ ] **Step 1: 写失败测试**

Create `tests/quotes.test.mjs`:

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { INDEX_SECIDS, parsePush2Quotes } from '../src/quotes.ts'

test('INDEX_SECIDS 含 4 个指数且顺序稳定', () => {
  assert.deepEqual(INDEX_SECIDS, ['1.000001', '0.399006', '1.000688', '1.000510'])
})

test('parsePush2Quotes 解析东财 ulist 响应', () => {
  const json = {
    data: {
      diff: [
        { f12: '000001', f14: '上证指数', f2: 3990.3, f3: 0.19 },
        { f12: '399006', f14: '创业板指', f2: 3705.56, f3: -0.93 },
        { f12: '000688', f14: '科创50', f2: 1790.87, f3: 0.11 },
        { f12: '000510', f14: '中证A500', f2: 5892.61, f3: -0.32 },
      ],
    },
  }
  const q = parsePush2Quotes(json)
  assert.equal(q.length, 4)
  assert.deepEqual(q[0], { name: '上证指数', price: 3990.3, changePct: 0.19 })
  assert.equal(q[3].name, '中证A500')
})

test('parsePush2Quotes 容错：缺字段丢弃、非数字转为 null', () => {
  const json = {
    data: { diff: [
      { f14: '无价', f3: 1 },
      { f14: '无涨跌', f2: 100 },
      { f14: '正常', f2: '1,234.56', f3: '-0.5' },
    ] },
  }
  const q = parsePush2Quotes(json)
  assert.equal(q.length, 1)
  assert.deepEqual(q[0], { name: '正常', price: 1234.56, changePct: -0.5 })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd E:/1target/SIEGPU/dsh-live-ticker && node --test tests/quotes.test.mjs`
Expected: FAIL（module not found）

- [ ] **Step 3: 实现 src/quotes.ts**

```ts
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
```

- [ ] **Step 4: 运行确认通过**

Run: `cd E:/1target/SIEGPU/dsh-live-ticker && node --test tests/quotes.test.mjs`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/src/quotes.ts dsh-live-ticker/tests/quotes.test.mjs
git -C E:/1target/SIEGPU commit -m "feat(dsh-live-ticker): 指数 secid + push2 响应解析（含单测）"
```

---

## Task 4: host apply——注册 /live-ticker/news 同源路由

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\src\index.ts`

- [ ] **Step 1: 实现 src/index.ts**

```ts
/**
 * dsh-live-ticker host 面：
 * 注册同源 JSON 路由 /live-ticker/news，代理东财新闻列表（30s 缓存）。
 * 路由模式参照 dsh-genui 的 webServer.register({kind:'prefix', path, handler})。
 */

import type { Context } from '@deepseek-ai/cordis'
import { NewsCache, fetchEfinanceNews } from './news.ts'

export const name = 'dsh-live-ticker'
export const inject = ['webServer']

const CACHE_TTL_MS = 30_000

export function apply(ctx: Context) {
  const cache = new NewsCache(CACHE_TTL_MS)

  ctx.on('internal/service', (name, value) => {
    if (name !== 'webServer' || value === undefined) return
    tryRegister(value)
  })

  function tryRegister(webServer: unknown) {
    const server = webServer as {
      register: (def: { kind: string; path: string; handler: (req: unknown) => Promise<unknown> }) => void
    }
    server.register({
      kind: 'prefix',
      path: '/live-ticker/news',
      handler: async () => {
        const cached = cache.get()
        if (cached) return { ok: true, ...cached }
        try {
          const snapshot = await fetchEfinanceNews()
          cache.set(snapshot)
          return { ok: true, ...snapshot }
        } catch (err) {
          const last = cache.last()
          return {
            ok: false,
            stale: true,
            items: last?.items ?? [],
            error: err instanceof Error ? err.message : String(err),
          }
        }
      },
    })
  }

  // webServer 可能在 apply 时已就绪（service 先于插件注册）
  const existing = (ctx as unknown as { get?: (k: string) => unknown }).get?.('webServer')
  if (existing !== undefined) tryRegister(existing)
}
```

> 说明：`webServer.register` 的 `kind: 'prefix'` 语义与 handler 请求对象形态，以 dsh-genui `lib/index.js` 第 1406 行为基准；若实现时 webServer 服务实际 key 或 register 签名不同，以运行时 `ctx.reflect.get('webServer', false)`（genui 同款）为准微调，不改动路由语义。

- [ ] **Step 2: 语法校验**

Run: `cd E:/1target/SIEGPU/dsh-live-ticker && node --experimental-strip-types --check src/index.ts`
Expected: 无输出（通过）。若当前 node 版本不支持 `--experimental-strip-types`，用 `D:\Program Files\DSH\.node\node.exe`（v22.23.2，支持 type stripping）执行。

- [ ] **Step 3: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/src/index.ts
git -C E:/1target/SIEGPU commit -m "feat(dsh-live-ticker): host 注册 /live-ticker/news 同源代理路由"
```

---

## Task 5: client 数据层（fetch.ts）

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\src\client\fetch.ts`

- [ ] **Step 1: 实现 src/client/fetch.ts**

```ts
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

export async function fetchNews(signal?: AbortSignal): Promise<NewsResult> {
  try {
    const res = await fetch('/live-ticker/news', { signal })
    if (!res.ok) return { snapshot: null, ok: false, error: `HTTP ${res.status}` }
    const body = await res.json() as { ok: boolean; items: unknown[]; fetchedAt: number; stale: boolean; error?: string }
    if (!body.ok) return { snapshot: null, ok: false, error: body.error }
    return {
      snapshot: { items: body.items as never, fetchedAt: body.fetchedAt, stale: body.stale },
      ok: true,
    }
  } catch (e) {
    return { snapshot: null, ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/src/client/fetch.ts
git -C E:/1target/SIEGPU commit -m "feat(dsh-live-ticker): client 数据层（push2 直连 + 同源新闻拉取）"
```

---

## Task 6: client 组件（TickerBar.tsx + index.tsx）

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\src\client\TickerBar.tsx`
- Create: `E:\1target\SIEGPU\dsh-live-ticker\src\client\index.tsx`

- [ ] **Step 1: 实现 TickerBar.tsx**

```tsx
/**
 * 两个可折叠行（默认展开）：
 * 1) 指数行：4 指数 2×2 网格，涨红跌绿，5s 轮询；
 * 2) 新闻行：横向滚动 ticker，最新在前，悬停暂停，60s 轮询。
 * 纯展示；visibilitychange 隐藏时暂停全部定时器。
 */

import React, { useEffect, useRef, useState } from 'react'
import type { Quote } from '../quotes.ts'
import { fetchQuotes, fetchNews } from './fetch.ts'

const QUOTE_POLL_MS = 5_000
const NEWS_POLL_MS = 60_000

export function TickerBar(): React.ReactElement {
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [quotesAt, setQuotesAt] = useState<number | null>(null)
  const [quotesOk, setQuotesOk] = useState(true)
  const [news, setNews] = useState<{ title: string; showTime: string; url: string }[]>([])
  const [newsStale, setNewsStale] = useState(false)
  const [newsAt, setNewsAt] = useState<number | null>(null)
  const [newsErr, setNewsErr] = useState('')
  const pausedRef = useRef(false)

  useEffect(() => {
    let alive = true
    let quoteTimer = 0
    let newsTimer = 0

    const onVisibility = () => {
      pausedRef.current = document.hidden
      if (!document.hidden) {
        refreshQuotes()
        refreshNews()
      }
    }

    async function refreshQuotes() {
      if (pausedRef.current || !alive) return
      const r = await fetchQuotes()
      if (!alive) return
      setQuotes(r.quotes)
      setQuotesAt(r.fetchedAt)
      setQuotesOk(r.ok)
      scheduleQuotes()
    }

    async function refreshNews() {
      if (pausedRef.current || !alive) return
      const r = await fetchNews()
      if (!alive) return
      if (r.snapshot) {
        setNews(r.snapshot.items as { title: string; showTime: string; url: string }[])
        setNewsStale(r.snapshot.stale)
        setNewsAt(r.snapshot.fetchedAt)
      }
      if (!r.ok && r.error) setNewsErr(r.error)
      scheduleNews()
    }

    function scheduleQuotes() {
      if (!alive) return
      quoteTimer = window.setTimeout(refreshQuotes, QUOTE_POLL_MS)
    }
    function scheduleNews() {
      if (!alive) return
      newsTimer = window.setTimeout(refreshNews, NEWS_POLL_MS)
    }

    refreshQuotes()
    refreshNews()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      alive = false
      clearTimeout(quoteTimer)
      clearTimeout(newsTimer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  const fmtTime = (t: number | null) => (t ? new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '')

  return (
    <div className="lt-ticker" style={styles.root}>
      <details open>
        <summary style={styles.summary}>
          <span style={styles.summaryTitle}>行情</span>
          <span style={styles.meta}>
            {quotesAt ? `更新于 ${fmtTime(quotesAt)}` : '加载中…'}
            {!quotesOk && quotes.length > 0 ? '（连接中断，显示上次数据）' : ''}
          </span>
        </summary>
        <div style={styles.quoteGrid}>
          {quotes.length === 0 && <span style={styles.empty}>暂无行情数据</span>}
          {quotes.map((q) => (
            <div key={q.name} style={styles.quoteCell}>
              <span style={styles.quoteName}>{q.name}</span>
              <span style={styles.quotePrice}>{q.price.toFixed(2)}</span>
              <span style={changeStyle(q.changePct)}>
                {q.changePct >= 0 ? '▲' : '▼'} {q.changePct >= 0 ? '+' : ''}{q.changePct.toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      </details>

      <details open>
        <summary style={styles.summary}>
          <span style={styles.summaryTitle}>财经快讯</span>
          <span style={styles.meta}>
            {newsAt ? `更新于 ${fmtTime(newsAt)}` : '加载中…'}
            {newsStale || newsErr ? `（${newsErr || '更新失败，显示上次数据'}）` : ''}
          </span>
        </summary>
        <div style={styles.tickerWrap} className="lt-ticker-scroll">
          <div style={styles.tickerInner} className="lt-ticker-inner">
            {news.length === 0 && <span style={styles.empty}>暂无新闻</span>}
            {news.map((n, i) => (
              <a key={`${n.url}-${i}`} href={n.url} target="_blank" rel="noreferrer" title={n.title} style={styles.tickerItem}>
                <span style={styles.tickerTime}>{n.showTime.slice(11)}</span>
                <span style={styles.tickerText}>{n.title}</span>
              </a>
            ))}
          </div>
        </div>
      </details>
    </div>
  )
}

function changeStyle(pct: number): React.CSSProperties {
  if (pct > 0) return { ...styles.quotePct, color: '#ef4444' }
  if (pct < 0) return { ...styles.quotePct, color: '#22c55e' }
  return { ...styles.quotePct, color: '#9ca3af' }
}

const styles: Record<string, React.CSSProperties> = {
  root: { fontSize: 13, color: 'var(--dsw-alias-label-primary, #e5e7eb)' },
  summary: { display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '4px 0', userSelect: 'none' },
  summaryTitle: { fontWeight: 600 },
  meta: { fontSize: 11, color: 'var(--dsw-alias-label-secondary, #9ca3af)' },
  quoteGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 6, paddingBottom: 6 },
  quoteCell: { display: 'flex', alignItems: 'baseline', gap: 8, padding: '4px 8px', borderRadius: 6, background: 'var(--dsw-alias-bg-elevated, rgba(128,128,128,.08))' },
  quoteName: { color: 'var(--dsw-alias-label-secondary, #9ca3af)' },
  quotePrice: { fontWeight: 700, fontVariantNumeric: 'tabular-nums' },
  quotePct: { fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums' },
  tickerWrap: { overflow: 'hidden', paddingBottom: 4 },
  tickerInner: { display: 'flex', gap: 20, whiteSpace: 'nowrap', animation: 'lt-ticker-scroll 40s linear infinite' },
  tickerItem: { display: 'inline-flex', gap: 6, alignItems: 'baseline', color: 'var(--dsw-alias-label-primary, #e5e7eb)', textDecoration: 'none', fontSize: 12 },
  tickerTime: { color: 'var(--dsw-alias-label-secondary, #9ca3af)', fontVariantNumeric: 'tabular-nums' },
  tickerText: {},
  empty: { color: 'var(--dsw-alias-label-secondary, #9ca3af)' },
}
```

- [ ] **Step 2: 实现 client/index.tsx（槽位注册）**

```tsx
/**
 * client 入口：注册 conversation.composer.dock 槽位。
 * 参照 dshmarket / dsh-i18n 的 slots.inject/register 形态。
 */

import React from 'react'
import type { Context } from '@deepseek-ai/cordis'
import { TickerBar } from './TickerBar.tsx'

export const name = 'dsh-live-ticker'
export const inject = ['slots']

export function apply(ctx: Context) {
  ctx.slots.inject('conversation.composer.dock', () =>
    ctx.slots.register({
      name: 'conversation.composer.dock',
      id: 'live-ticker',
      order: 100,
      label: () => 'live-ticker',
    }, () => React.createElement(TickerBar)),
  )
}
```

- [ ] **Step 3: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/src/client/TickerBar.tsx dsh-live-ticker/src/client/index.tsx
git -C E:/1target/SIEGPU commit -m "feat(dsh-live-ticker): client 组件（折叠行情行 + 滚动新闻行）与槽位注册"
```

---

## Task 7: client 构建脚本（build-client.mjs → lib/client.js）

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\scripts\build-client.mjs`

- [ ] **Step 1: 实现构建脚本**

```js
/**
 * 用 esbuild 把 src/client 打包成 DSH client 插件格式：
 * window.__ModuleLoader__.load({ id, factory })。
 * 参照 dshmarket 的 tsdown + normalize-client-banner 产物形态。
 */
import { build } from 'esbuild'
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = dirname(dirname(fileURLToPath(import.meta.url)))

const result = await build({
  entryPoints: [join(root, 'src/client/index.tsx')],
  bundle: true,
  format: 'iife',
  platform: 'browser',
  jsx: 'automatic',
  external: ['react', 'react/jsx-runtime'],
  outfile: join(root, 'lib/_client_raw.js'),
  write: true,
  logLevel: 'silent',
})

const raw = readFileSync(join(root, 'lib/_client_raw.js'), 'utf8')
const banner = `window.__ModuleLoader__.load({
  id: "dsh-live-ticker",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
${raw.split('\n').map((l) => '    ' + l).join('\n')}
    return module.exports;
  }
});
`
mkdirSync(join(root, 'lib'), { recursive: true })
writeFileSync(join(root, 'lib/client.js'), banner)
// 清理中间产物
try { import('node:fs').then((fs) => fs.unlinkSync(join(root, 'lib/_client_raw.js'))) } catch { /* ignore */ }
console.log('built lib/client.js', banner.length, 'bytes')
```

- [ ] **Step 2: 构建并校验产物**

Run: `cd E:/1target/SIEGPU/dsh-live-ticker && node --experimental-strip-types scripts/build-client.mjs`（若 node 不支持，用 `D:\Program Files\DSH\.node\node.exe`）
Expected: `built lib/client.js ... bytes`，且 `lib/client.js` 以 `window.__ModuleLoader__.load({` 开头。

> 注：esbuild 二进制在 DSH 仓库 `node_modules` 可用（`D:\Program Files\DSH\node_modules\.bin\esbuild.cmd`）。若本目录未安装 esbuild，在 package.json devDependencies 加 `esbuild` 并用 pnpm 安装，或临时用 DSH 仓库的 esbuild 路径。构建产物 `lib/client.js` 提交入库，运行时无需再构建。

- [ ] **Step 3: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/scripts/build-client.mjs dsh-live-ticker/lib/client.js
git -C E:/1target/SIEGPU commit -m "build(dsh-live-ticker): client 构建脚本与 lib/client.js 产物"
```

---

## Task 8: README + 全量测试 + 安装验收

**Files:**
- Create: `E:\1target\SIEGPU\dsh-live-ticker\README.md`

- [ ] **Step 1: 写 README.md**

```markdown
# dsh-live-ticker

DSH 插件：对话框底部（输入框卡片下方）两个可折叠行——4 个指数实时行情 + 东财财经新闻滚动。

## 数据源
- 指数：东方财富 push2（浏览器直连，CORS `*`），5s 轮询。上证指数 / 创业板指 / 科创50 / 中证A500（`1.000510`）。
- 新闻：东方财富新闻列表（host 代理，同源 `/live-ticker/news`，30s 缓存），60s 轮询。

## 安装
```sh
dsh plugin --profile web add "file:E:/1target/SIEGPU/dsh-live-ticker"
# 重启 dsh --profile web
```

## 卸载
```sh
dsh plugin --profile web remove dsh-live-ticker
```

## 开发
- host：`src/index.ts`（tsx 加载）
- client：`src/client/` → `node scripts/build-client.mjs` → `lib/client.js`
- 测试：`node --test tests/`
```

- [ ] **Step 2: 跑全量单测**

Run: `cd E:/1target/SIEGPU/dsh-live-ticker && node --test tests/`
Expected: PASS（news 3 tests + quotes 3 tests）

- [ ] **Step 3: 安装到 web profile**

Run:
```powershell
dsh plugin --profile web add "file:E:/1target/SIEGPU/dsh-live-ticker"
```
Expected: pnpm 成功安装，package.json dependencies 出现 `dsh-live-ticker: file:...`，bundle 列表追加 `dsh-live-ticker`。

- [ ] **Step 4: 重启并人工验收清单**（需重启 `dsh --profile web`）

- [ ] 对话底部输入框下方出现两个折叠行，默认展开
- [ ] 4 个指数数值与东方财富网页一致，涨红跌绿正确
- [ ] 新闻行横向滚动、悬停暂停、点击打开原文
- [ ] 标签页隐藏 10s 再回来：指数立即刷新且无堆积轮询
- [ ] 断网时显示"连接中断/更新失败"stale 态，恢复后自愈
- [ ] 与 dshmarket / dsh-i18n / dsh-genui 等已装插件无槽位冲突（composer.dock 为 list 槽可共存）

- [ ] **Step 5: Commit**

```bash
git -C E:/1target/SIEGPU add dsh-live-ticker/README.md
git -C E:/1target/SIEGPU commit -m "docs(dsh-live-ticker): README + 验收清单"
```

---

## 自审记录（writing-plans 要求）

- **Spec 覆盖**：设计 §2.1 指数源（Task 3, 5）、§2.2 新闻源（Task 2, 4, 5）、§4.1 composer.dock 槽位（Task 6）、§5 UI 细节（Task 6：折叠/涨跌色/滚动/悬停暂停/visibilitychange/主题变量/宽度约束）、§6 数据流与错误处理（Task 4, 5, 6：stale 标记、失败回退）、§8 测试（Task 2/3 单测 + Task 8 人工清单）、§9 安装（Task 8）、§10 风险（webServer.register 签名在 Task 4 注释中给降级；腾讯备源按设计 YAGNI 暂不做）。
- **占位符扫描**：无 TBD/TODO；webServer 签名差异处理在 Task 4 用运行时探测降级写明，非占位符。
- **类型一致性**：`NewsItem`/`NewsSnapshot`/`Quote`/`INDEX_SECIDS`/`QUOTES_URL` 在 Task 2/3 定义，Task 5/6 复用同名同形；`fetchQuotes`/`fetchNews`/`parsePush2Quotes`/`parseEfinanceNews` 名称全计划一致；`news.fetchImpl` 参数在 Task 4 调用时省略（默认 fetch），一致。
