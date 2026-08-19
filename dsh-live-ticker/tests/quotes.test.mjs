import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { INDEX_CODES, parseTencentQuotes } from '../src/quotes.ts'

const FIXTURE = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'tencent-quotes.txt')

test('INDEX_CODES 含 4 个指数且顺序稳定', () => {
  assert.deepEqual(INDEX_CODES, ['sh000001', 'sz399006', 'sh000688', 'sh000510'])
})

test('parseTencentQuotes 解析腾讯 qt.gtimg.cn 真实响应（fixture）', () => {
  const text = readFileSync(FIXTURE, 'utf8')
  const q = parseTencentQuotes(text)
  assert.equal(q.length, 4)
  assert.equal(q[0].name, '上证指数')
  assert.equal(q[1].name, '创业板指')
  assert.equal(q[2].name, '科创50')
  assert.equal(q[3].name, '中证A500')
  // 字段索引正确：现价与涨跌幅均为有限数（不依赖具体数值，避免随行情波动失败）
  for (const item of q) {
    assert.ok(Number.isFinite(item.price) && item.price > 0, `${item.name} price`)
    assert.ok(Number.isFinite(item.changePct) && Math.abs(item.changePct) < 100, `${item.name} changePct`)
  }
})

test('parseTencentQuotes 容错：缺字段丢弃、非数字丢弃、空串不等于 0', () => {
  // 涨跌幅在 f[32]：f[0..2]=标志/名称/代码，f[3]=现价，f[4..31]=28 个填充字段，f[32]=涨跌幅
  const pad = '0~'.repeat(28)
  const valid = `v_x1="1~正常~002~1234.56~${pad}-1.5~";`
  const badPrice = `v_x2="1~无价~003~abc~${pad}-1.5~";`     // price 非数字
  const badPct = `v_x3="1~无涨跌~004~1234.56~${pad}~";`        // f[32] 空（Number('')===0 的陷阱）
  const q = parseTencentQuotes(valid + badPrice + badPct)
  assert.equal(q.length, 1)
  assert.deepEqual(q[0], { name: '正常', price: 1234.56, changePct: -1.5 })
})
