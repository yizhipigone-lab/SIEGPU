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
