/**
 * 两条展示条（都挂 conversation.composer.dock，输入框下方，正常文档流）：
 * 1) QuotesBar 指数条：居中横排，5s 轮询；
 * 2) NewsBar 新闻条：对话窗口内横向滚动（100s 慢速），悬停暂停，60s 轮询。
 * visibilitychange 隐藏时暂停全部定时器。
 */

import React, { useEffect, useState } from 'react'
import type { Quote } from '../quotes.ts'
import { fetchQuotes, fetchNews } from './fetch.ts'

const QUOTE_POLL_MS = 5_000
const NEWS_POLL_MS = 60_000

/** 新闻条像素高度，index.tsx 注入座位留白时用同一个值。 */
export const NEWS_BAR_H = 26

// ---------- 指数条：输入框正下方，居中（composer.dock 槽位，同雪球指数条） ----------
export function QuotesBar(): React.ReactElement {
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [quotesOk, setQuotesOk] = useState(true)

  useEffect(() => {
    let alive = true
    let timer = 0
    const pausedRef = { current: false }

    const onVisibility = () => {
      pausedRef.current = document.hidden
      if (!document.hidden) void refresh()
    }

    async function refresh() {
      if (pausedRef.current || !alive) return
      const r = await fetchQuotes()
      if (!alive) return
      if (r.quotes.length > 0) setQuotes(r.quotes)
      setQuotesOk(r.ok)
      timer = window.setTimeout(refresh, QUOTE_POLL_MS)
    }

    void refresh()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      alive = false
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return (
    <div style={styles.quotesRoot} title={quotesOk ? '' : '连接中断，显示上次数据'}>
      {quotes.length === 0 && <span style={styles.empty}>暂无行情数据</span>}
      {quotes.map((q) => (
        <div key={q.name} style={styles.quoteChip}>
          <span style={styles.quoteName}>{q.name}</span>
          <span style={styles.quotePrice}>{q.price.toFixed(2)}</span>
          <span style={changeStyle(q.changePct)}>
            {q.changePct > 0 ? '▲' : q.changePct < 0 ? '▼' : '—'} {q.changePct > 0 ? '+' : ''}{q.changePct.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  )
}

// ---------- 新闻条：视口最下方整宽，横向滚动（shell.overlay 固定条） ----------
export function NewsBar(): React.ReactElement {
  const [news, setNews] = useState<{ title: string; showTime: string; url: string }[]>([])

  useEffect(() => {
    let alive = true
    let timer = 0
    const pausedRef = { current: false }

    const onVisibility = () => {
      pausedRef.current = document.hidden
      if (!document.hidden) void refresh()
    }

    async function refresh() {
      if (pausedRef.current || !alive) return
      const r = await fetchNews()
      if (!alive) return
      const items = r.snapshot?.items
      if (Array.isArray(items) && items.length > 0) {
        setNews(items as { title: string; showTime: string; url: string }[])
      }
      timer = window.setTimeout(refresh, NEWS_POLL_MS)
    }

    void refresh()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      alive = false
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return (
    <div style={styles.newsRoot} className="lt-news-root">
      <style>{`
        .lt-ticker-inner { animation: lt-ticker-scroll 100s linear infinite; }
        .lt-news-root:hover .lt-ticker-inner { animation-play-state: paused; }
        @keyframes lt-ticker-scroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
      <div style={styles.tickerInner} className="lt-ticker-inner">
        {news.length === 0 && <span style={styles.empty}>暂无新闻</span>}
        {[...news, ...news].map((n, i) => (
          <a key={`${n.url}-${i}`} href={n.url} target="_blank" rel="noreferrer" title={n.title} style={styles.tickerItem}>
            <span style={styles.tickerTime}>{typeof n.showTime === 'string' ? n.showTime.slice(11) : ''}</span>
            <span>{n.title}</span>
          </a>
        ))}
      </div>
    </div>
  )
}

function changeStyle(pct: number): React.CSSProperties {
  if (pct > 0) return { ...styles.quotePct, color: 'var(--dsh-up, #ef4444)' }
  if (pct < 0) return { ...styles.quotePct, color: 'var(--dsh-down, #22c55e)' }
  return { ...styles.quotePct, color: 'var(--dsw-alias-label-secondary, #9ca3af)' }
}

const styles: Record<string, React.CSSProperties> = {
  // 指数条：正常文档流（槽位本身在卡片下方），内容水平居中。
  quotesRoot: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexWrap: 'nowrap',
    columnGap: 22,
    overflow: 'hidden',
    whiteSpace: 'nowrap',
    fontSize: 13,
    padding: '2px 0',
    color: 'var(--dsw-alias-label-primary, #e5e7eb)',
  },
  quoteChip: { display: 'inline-flex', alignItems: 'baseline', gap: 6, whiteSpace: 'nowrap', fontSize: 13 },
  quoteName: { color: 'var(--dsw-alias-label-secondary, #9ca3af)', fontSize: 12 },
  quotePrice: { fontWeight: 700, fontVariantNumeric: 'tabular-nums' },
  quotePct: { fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums' },
  // 新闻条：对话窗口内正常文档流（composer.dock 槽位，输入框下方），不浮层、不遮挡其他 UI。
  newsRoot: {
    display: 'flex',
    alignItems: 'center',
    overflow: 'hidden',
    whiteSpace: 'nowrap',
    fontSize: 12,
    height: NEWS_BAR_H,
    padding: '2px 0',
    borderTop: '1px solid var(--dsw-alias-border-l1, #374151)',
    color: 'var(--dsw-alias-label-primary, #e5e7eb)',
  },
  tickerInner: { display: 'flex', gap: 20, whiteSpace: 'nowrap', alignItems: 'baseline' },
  tickerItem: { display: 'inline-flex', gap: 6, alignItems: 'baseline', color: 'var(--dsw-alias-label-primary, #e5e7eb)', textDecoration: 'none', fontSize: 12 },
  tickerTime: { color: 'var(--dsw-alias-label-secondary, #9ca3af)', fontVariantNumeric: 'tabular-nums' },
  empty: { color: 'var(--dsw-alias-label-secondary, #9ca3af)', padding: '0 8px' },
}
