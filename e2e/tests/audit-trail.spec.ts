import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 操作留痕前端视图（新手友好专项⑦）—— 端到端铁律：
//   合同做一次变更（写入 audit_logs.entity_type='contract'）→ 详情抽屉「操作记录」区渲染中文化动作。
// 权限口径：/api/audit 仅 ADMIN/FINANCE_DIRECTOR，故用 cfo（财务总监）验证。

const api = '/api'
const RUN = Date.now().toString(36)
const contractNo = `AU-${RUN}`

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

test('合同详情「操作记录」渲染中文化变更动作', async ({ page, request }) => {
  const headers = await apiLogin(request, 'cfo')

  // 造主数据 + 项目 + 销售合同
  const cust = await request.post(`${api}/customers`, { headers, data: { name: `审计客户-${RUN}` } })
  expect(cust.ok()).toBeTruthy()
  const custId = (await cust.json()).id
  const proj = await request.post(`${api}/projects`, { headers, data: { name: `审计项目-${RUN}` } })
  expect(proj.ok()).toBeTruthy()
  const projId = (await proj.json()).id
  const ct = await request.post(`${api}/contracts`, {
    headers, data: { project_id: projId, type: 'SALES', party_id: custId, amount: 1_000_000, contract_no: contractNo },
  })
  expect(ct.ok()).toBeTruthy()
  const ctId = (await ct.json()).id

  // 合同变更 → 写入 audit_logs（entity_type='contract', action='UPDATE'）
  const amd = await request.post(`${api}/contracts/${ctId}/amendments`, {
    headers, data: { change_type: '金额变更', new_amount: 1_200_000, reason: 'e2e 审计' },
  })
  expect(amd.ok(), '合同变更应成功').toBeTruthy()

  // UI：cfo 打开合同详情抽屉 → 操作记录区可见「变更」
  await uiLogin(page, 'cfo')
  await page.goto('/master/contracts')
  const row = page.locator('.n-data-table tbody tr').filter({ hasText: contractNo })
  await expect(row).toBeVisible({ timeout: 8000 })
  await row.locator('button[title="详情"]').click()

  const trail = page.locator('[data-testid="audit-trail"]')
  await expect(trail).toBeVisible()
  await expect(trail).toContainText('变更')
  await expect(trail).toContainText('财务总监') // 操作人显示名（cfo）
})
