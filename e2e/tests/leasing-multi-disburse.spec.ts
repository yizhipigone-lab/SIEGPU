import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 金租分次放款（端到端铁律）：一次批准 → 多笔放款，前端「放款记录」区正确展示。
// API 登记两笔放款（覆盖 add_disbursement 端点），UI 验证放款记录区渲染 + 每笔金额。
const api = '/api'
const RUN = Date.now().toString(36)
// 每次运行唯一申请额（避免与历史运行残留同金额撞车 strict-mode），格式与前端 money() 一致
const UNIQUE_AMOUNT = Number(String(Date.now()).slice(-9))
const AMOUNT_STR = UNIQUE_AMOUNT.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

async function apiLogin(request: APIRequestContext, username: string) {
  const res = await request.post(`${api}/auth/login`, { form: { username, password: 'sie123' } })
  expect(res.ok(), `API 登录失败: ${username}`).toBeTruthy()
  const { access_token } = await res.json()
  return { Authorization: `Bearer ${access_token}` }
}

async function uiLogin(page: Page, username: string) {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill(username)
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/, { timeout: 8000 })
}

test('金租详情「放款记录」区展示多笔放款', async ({ page, request }) => {
  const headers = await apiLogin(request, 'cfo')

  // 造数：资金供应商 + 设备型号 + 项目 + 订单 + 采购验收(通过)
  const sup = await request.post(`${api}/suppliers`, { headers, data: { name: `E2E-金租-${RUN}`, type: '资金供应商' } })
  expect(sup.ok()).toBeTruthy()
  const supId = (await sup.json()).id
  const eq = await request.post(`${api}/equipment-models`, { headers, data: { name: `E2E-型号-${RUN}`, category: '大卡', gpu_type: 'A100' } })
  expect(eq.ok()).toBeTruthy()
  const eqId = (await eq.json()).id
  const proj = await request.post(`${api}/projects`, { headers, data: { name: `E2E-分次放款-${RUN}` } })
  expect(proj.ok()).toBeTruthy()
  const projId = (await proj.json()).id
  const ord = await request.post(`${api}/orders`, { headers, data: { project_id: projId, equipment_model_id: eqId, quantity: 1, unit_price: 1 } })
  expect(ord.ok()).toBeTruthy()
  const ordId = (await ord.json()).id
  const acc = await request.post(`${api}/acceptances`, { headers, data: { project_id: projId, acceptance_type: '采购验收', order_id: ordId } })
  expect(acc.ok()).toBeTruthy()
  const accId = (await acc.json()).id
  expect((await request.post(`${api}/acceptances/${accId}/approve`, { headers })).ok()).toBeTruthy()

  // 建金租申请（唯一申请额用于定位行）
  const lp = await request.post(`${api}/leasing/processes`, { headers, data: {
    project_id: projId, supplier_id: supId, total_amount: UNIQUE_AMOUNT,
    annual_rate: 0.04, term_periods: 12, payment_freq: '月', repayment_method: '等额本息',
  } })
  expect(lp.ok()).toBeTruthy()
  const lpId = (await lp.json()).id

  // 登记两笔放款（关联同一批采购验收，每笔独立生成 12 期还款计划）
  for (const [amount, date] of [[10_000_000, '2026-08-01'], [5_000_000, '2026-09-01']]) {
    const d = await request.post(`${api}/leasing/processes/${lpId}/disbursements`, {
      headers, data: { amount, disbursement_date: date, acceptance_id: accId },
    })
    expect(d.ok(), `放款 ${amount} 应成功`).toBeTruthy()
  }

  // UI：cfo 打开金租详情 → 「放款记录」区展示 2 笔
  await uiLogin(page, 'cfo')
  await page.goto('/leasing')
  const row = page.locator('.n-data-table tbody tr').filter({ hasText: AMOUNT_STR })
  await expect(row).toBeVisible({ timeout: 8000 })
  await row.getByRole('button', { name: '详情' }).click()

  await expect(page.getByText('放款记录（2 笔）')).toBeVisible({ timeout: 8000 })
  await expect(page.getByText('10,000,000.00')).toBeVisible()
  await expect(page.getByText('5,000,000.00')).toBeVisible()
  await expect(page.getByRole('button', { name: '新增放款' })).toBeVisible()
})
