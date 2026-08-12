import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 二期 W11-12 付款三重管控 —— 端到端（端到端铁律）：
//   UI 新增付款申请（1000，预付款冲抵 300）→ 审批中心通过 → 登记付款（现金 700 落流水）
//   → 核销（两张采购发票 400+300 多行）→ 核销记录可见
//   → API 追值：发票已核销+paid_date / 设备预付款 FIFO 抵扣 300 / 核销行 2 条。
// 共享 dev 库无隔离：项目 `E2E-` 前缀、供应商 `E2E供应商`、发票 `INV-` 前缀，cleanup_e2e 清理
// （payment_requests 有 project_id 走级联；approvals/payment_settlements 孤儿行兜底见下）。

const API = '/api'
const RUN = Date.now().toString(36)

async function apiLogin(request: APIRequestContext, username = 'cfo', password = 'sie123') {
  const res = await request.post(`${API}/auth/login`, { form: { username, password } })
  expect(res.ok(), `API 登录失败: ${username}`).toBeTruthy()
  const { access_token } = await res.json()
  return { Authorization: `Bearer ${access_token}` }
}
async function uiLogin(page: Page, username = 'cfo') {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill(username)
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/, { timeout: 8000 })
}

test('付款管控：申请(冲抵预付款) → 审批通过 → 登记 → 多发票核销 → 追值', async ({ page, request }) => {
  const headers = await apiLogin(request)

  // ---- 备数：项目 + 供应商 + 采购合同 + 两张发票(400/300) + 预付款设备(300) ----
  const proj = await (await request.post(`${API}/projects`, {
    headers, data: { name: `E2E-付款-${RUN}` },
  })).json()
  const sup = await (await request.post(`${API}/suppliers`, {
    headers, data: { name: `E2E供应商-付款-${RUN}`, type: '设备供应商' },
  })).json()
  const contract = await (await request.post(`${API}/contracts`, {
    headers, data: { project_id: proj.id, type: 'PURCHASE', party_id: sup.id, amount: 10000000 },
  })).json()
  const invA = await (await request.post(`${API}/invoices`, {
    headers, data: { contract_id: contract.id, amount: 400, invoice_no: `INV-E2E-A-${RUN}` },
  })).json()
  const invB = await (await request.post(`${API}/invoices`, {
    headers, data: { contract_id: contract.id, amount: 300, invoice_no: `INV-E2E-B-${RUN}` },
  })).json()
  const model = await (await request.post(`${API}/equipment-models`, {
    headers, data: { name: `E2E-型号-付款-${RUN}`, category: '大卡', gpu_count: 8 },
  })).json()
  const device = await (await request.post(`${API}/devices`, {
    headers, data: { project_id: proj.id, equipment_model_id: model.id, purchase_value: 960000, prepayment_amount: 300, ownership: '表内自有' },
  })).json()

  // ---- UI：新增付款申请（1000，冲抵 300）----
  await uiLogin(page)
  await page.goto('/payments')
  await expect(page.getByRole('heading', { name: '付款管控' })).toBeVisible()
  await page.getByRole('button', { name: '新增付款申请' }).click()
  let modal = page.locator('.n-modal').filter({ hasText: '新增付款申请' })
  await modal.waitFor()
  const projItem = modal.locator('.n-form-item', { hasText: '选择项目' })
  await projItem.locator('.n-base-selection').click()
  await page.waitForTimeout(300)
  await projItem.locator('input').fill(`E2E-付款-${RUN}`)
  await page.waitForTimeout(400)
  await page.locator('.n-base-select-option', { hasText: `E2E-付款-${RUN}` }).filter({ visible: true }).first().click()
  await modal.locator('.n-form-item', { hasText: '金额' }).locator('input').fill('1000')
  await modal.locator('.n-form-item', { hasText: '预付款冲抵' }).locator('input').fill('300')
  await modal.locator('.n-form-item', { hasText: '事由' }).locator('input').click() // blur 同步 NInputNumber
  await modal.locator('.n-form-item', { hasText: '事由' }).locator('input').fill(`E2E付款-${RUN}`)
  await modal.getByRole('button', { name: '提交审批' }).click()
  await expect(page.locator('.n-message', { hasText: '待审批' })).toBeVisible({ timeout: 8000 })
  await modal.waitFor({ state: 'hidden', timeout: 15000 })

  // ---- 审批中心：通过（锚点=项目名，标题含「付款申请 1000（项目 E2E-付款-{RUN}）」）----
  const pendingTag = page.locator('.n-tag', { hasText: `E2E-付款-${RUN}` })
  await expect(pendingTag).toBeVisible({ timeout: 8000 })
  await pendingTag.getByRole('button', { name: '通过' }).click()
  await expect(page.locator('.n-message', { hasText: '已通过' })).toBeVisible({ timeout: 8000 })

  // ---- 登记付款 ----
  const approvedTag = page.locator('.n-tag', { hasText: '申请 1,000.00' })
  await expect(approvedTag).toBeVisible({ timeout: 8000 })
  await approvedTag.getByRole('button', { name: '登记付款' }).click()
  modal = page.locator('.n-modal').filter({ hasText: '登记付款' })
  await modal.waitFor()
  await modal.locator('.n-form-item', { hasText: '付款日期' }).locator('input').fill('2026-08-13')
  await page.keyboard.press('Enter') // n-date-picker 回车确认（不可 Escape，会关弹窗）
  await modal.getByRole('button', { name: '登记' }).click()
  await expect(page.locator('.n-message', { hasText: '已登记付款' })).toBeVisible({ timeout: 8000 })

  // ---- 核销：两行（发票A 400 + 发票B 300 = 700 现金流水）----
  const paidTag = page.locator('.n-tag', { hasText: '已付 1,000.00' })
  await expect(paidTag).toBeVisible({ timeout: 8000 })
  await paidTag.getByRole('button', { name: '核销' }).click()
  modal = page.locator('.n-modal').filter({ hasText: '核销（可多行）' })
  await modal.waitFor()
  const row0 = modal.locator('.alloc-row').nth(0)
  await row0.locator('.n-base-selection').click()
  await page.waitForTimeout(300)
  await row0.locator('input').first().fill(`INV-E2E-A-${RUN}`)
  await page.waitForTimeout(400)
  await page.locator('.n-base-select-option', { hasText: `INV-E2E-A-${RUN}` }).filter({ visible: true }).first().click()
  await row0.locator('.n-input-number input').fill('400')
  await modal.getByRole('button', { name: '+ 加一行' }).click()
  const row1 = modal.locator('.alloc-row').nth(1)
  await row1.locator('.n-base-selection').click()
  await page.waitForTimeout(300)
  await row1.locator('input').first().fill(`INV-E2E-B-${RUN}`)
  await page.waitForTimeout(400)
  await page.locator('.n-base-select-option', { hasText: `INV-E2E-B-${RUN}` }).filter({ visible: true }).first().click()
  await row1.locator('.n-input-number input').fill('300')
  await modal.getByRole('button', { name: '+ 加一行' }).click() // blur 第二行金额
  await page.locator('.n-modal').filter({ hasText: '核销（可多行）' }).getByRole('button', { name: '核销', exact: true }).click()
  await expect(page.locator('.n-message', { hasText: '核销完成' })).toBeVisible({ timeout: 8000 })

  // 核销记录卡出现「我的流水」的行（唯一锚点=流水号前 8 位；全套并发下别 spec 的核销行同在表中，禁数总数）
  const prs = await (await request.get(`${API}/payment-requests`, {
    headers, params: { project_id: proj.id },
  })).json()
  const txnId: string = prs.items[0].capital_transaction_id
  const settCard = page.locator('.n-card', { hasText: '核销记录' })
  await expect(settCard).toContainText(txnId.slice(0, 8), { timeout: 8000 })

  // ---- API 追值 ----
  for (const [inv, amt] of [[invA, 400], [invB, 300]] as const) {
    const cur = await (await request.get(`${API}/invoices/pool`, { headers })).json()
    const mine = cur.items.find((i: any) => i.id === inv.id)
    expect(mine.status).toBe('已核销')
    expect(Number(mine.matched_amount)).toBe(amt)
  }
  const devs = await (await request.get(`${API}/devices`, { headers, params: { project_id: proj.id } })).json()
  const mineDev = devs.items.find((d: any) => d.id === device.id)
  expect(Number(mineDev.prepayment_settled_amount)).toBe(300)  // 冲抵 FIFO 抵扣（单源）
  expect(mineDev.prepayment_settled).toBe(true)
  const setts = await (await request.get(`${API}/payment-settlements`, { headers })).json()
  const mySetts = setts.items.filter((s: any) => [invA.id, invB.id].includes(s.invoice_id))
  expect(mySetts.length).toBe(2)
})
