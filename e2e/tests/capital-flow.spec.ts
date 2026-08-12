import { test, expect } from '@playwright/test'

// 全程走 baseURL(nginx:8088) → /api 反代 backend → db，真实端到端链路。
test('登录 → 建项目 → 记流水 → 对账（资金池净头寸）', async ({ request }) => {
  const api = '/api'
  // RUN 后缀：共享 dev-DB 无隔离，每次跑造唯一项目名，globalTeardown 据前缀 E2E- 清理。
  const RUN = Date.now().toString(36)

  // 1) 登录拿 token
  const loginRes = await request.post(`${api}/auth/login`, {
    form: { username: 'cfo', password: 'sie123' },
  })
  expect(loginRes.ok()).toBeTruthy()
  const { access_token } = await loginRes.json()
  const H = { Authorization: `Bearer ${access_token}` }

  // 2) 建项目
  const projRes = await request.post(`${api}/projects`, {
    headers: H,
    data: { name: `E2E-商机5090-${RUN}` },
  })
  expect(projRes.ok()).toBeTruthy()
  const proj = await projRes.json()
  expect(proj.id).toBeTruthy()

  // 3) 记流水：自有 500 万 IN + 银行流贷 200 万 IN + 付尾款 100 万 OUT
  const postTx = (body: Record<string, unknown>) =>
    request.post(`${api}/capital/transactions`, {
      headers: H,
      data: { ...body, project_id: proj.id },
    })
  expect((await postTx({ source_type: '自有资金', direction: 'IN', amount: 5_000_000, transaction_date: '2026-01-01' })).ok()).toBeTruthy()
  expect((await postTx({ source_type: '银行流贷', direction: 'IN', amount: 2_000_000, transaction_date: '2026-01-02' })).ok()).toBeTruthy()
  expect((await postTx({ source_type: '银行流贷', direction: 'OUT', amount: 1_000_000, transaction_date: '2026-01-03', category: '付尾款' })).ok()).toBeTruthy()

  // 4) 对账：该项目净头寸 = 7M - 1M = 6M（用项目级断言，抗历史数据污染）
  const sumRes = await request.get(`${api}/capital/summary`, { headers: H })
  const summary = await sumRes.json()
  const mine = summary.per_project.find((p: { project_id: string }) => p.project_id === proj.id)
  expect(mine, '新建项目应出现在汇总中').toBeTruthy()
  expect(Number(mine.net_position)).toBe(6_000_000)
})
