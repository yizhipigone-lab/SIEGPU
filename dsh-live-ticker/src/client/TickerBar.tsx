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
      // 成功才覆盖；失败保留上次值（设计 §5：失败保留上次值并显示 stale 标记）
      if (r.ok && r.quotes.length > 0) {
        setQuotes(r.quotes)
        setQuotesAt(r.fetchedAt)
      }
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
        setNewsErr('')
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
    <>
      <style>{`
        .lt-ticker-inner { animation: lt-ticker-scroll 40s linear infinite; }
        .lt-ticker-scroll:hover .lt-ticker-inner { animation-play-state: paused; }
        @keyframes lt-ticker-scroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
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
                {q.changePct > 0 ? '▲' : q.changePct < 0 ? '▼' : '—'} {q.changePct > 0 ? '+' : ''}{q.changePct.toFixed(2)}%
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
            {[...news, ...news].map((n, i) => (
              <a key={`${n.url}-${i}`} href={n.url} target="_blank" rel="noreferrer" title={n.title} style={styles.tickerItem}>
                <span style={styles.tickerTime}>{n.showTime.slice(11)}</span>
                <span>{n.title}</span>
              </a>
            ))}
          </div>
        </div>
      </details>
      </div>
    </>
  )
}

function changeStyle(pct: number): React.CSSProperties {
  if (pct > 0) return { ...styles.quotePct, color: 'var(--dsh-up, #ef4444)' }
  if (pct < 0) return { ...styles.quotePct, color: 'var(--dsh-down, #22c55e)' }
  return { ...styles.quotePct, color: 'var(--dsw-alias-label-secondary, #9ca3af)' }
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
  tickerInner: { display: 'flex', gap: 20, whiteSpace: 'nowrap' },
  tickerItem: { display: 'inline-flex', gap: 6, alignItems: 'baseline', color: 'var(--dsw-alias-label-primary, #e5e7eb)', textDecoration: 'none', fontSize: 12 },
  tickerTime: { color: 'var(--dsw-alias-label-secondary, #9ca3af)', fontVariantNumeric: 'tabular-nums' },
  empty: { color: 'var(--dsw-alias-label-secondary, #9ca3af)' },
}
