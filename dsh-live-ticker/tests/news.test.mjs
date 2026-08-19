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
