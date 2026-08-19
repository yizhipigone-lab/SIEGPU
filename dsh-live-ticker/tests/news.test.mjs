import test from 'node:test'
import assert from 'node:assert/strict'
import { parseEfinanceNews, NewsCache, fetchEfinanceNews } from '../src/news.ts'

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
      { title: '   ', showTime: '2026-08-19 00:02', url: 'http://x/4' },
    ] },
  }
  const items = parseEfinanceNews(json)
  assert.equal(items.length, 1)
  assert.equal(items[0].title, '全')
})

test('NewsCache 命中与过期', () => {
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

test('NewsCache last() 过期后仍保留快照（回退路径）', () => {
  const cache = new NewsCache(30_000)
  cache.set({ items: [], fetchedAt: Date.now() - 60_000, stale: true })
  assert.equal(cache.get(), null)
  assert.ok(cache.last())
  assert.equal(cache.last().stale, true)
})

test('fetchEfinanceNews 成功返回快照', async () => {
  const fake = async () => ({
    ok: true,
    json: async () => ({ data: { list: [{ title: 'T', showTime: '2026-08-19 07:50:32', url: 'http://x' }] } }),
  })
  const r = await fetchEfinanceNews(fake)
  assert.deepEqual(r.items, [{ title: 'T', showTime: '2026-08-19 07:50', url: 'http://x' }])
  assert.equal(r.stale, false)
  assert.equal(typeof r.fetchedAt, 'number')
})

test('fetchEfinanceNews 非 200 抛错', async () => {
  const fake = async () => ({ ok: false, status: 500 })
  await assert.rejects(fetchEfinanceNews(fake), /HTTP 500/)
})

test('fetchEfinanceNews 网络异常抛错', async () => {
  const fake = () => { throw new Error('boom') }
  await assert.rejects(fetchEfinanceNews(fake), /boom/)
})
