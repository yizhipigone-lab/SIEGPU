import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 二期 W9-10 合同深化 + 预付款 —— 端到端（端到端铁律）：
//   UI 合同详情抽屉：聚合 tabs（发票/计费单/变更记录/终止记录）→ 合同变更（金额，快照留痕）
//   → 变更记录 tab 追值 + 合同金额已改 → 预付款台账页（设备预付款余额）
//   → API 追值：amendment 快照 / 合同新金额 / EBS 出站 / 预付款余额单源。
// 共享 dev 库无隔离：项目 `E2E-` 前缀、客户 `客户-E2E`、合同号 `HT-F` 前缀，cleanup_e2e 清理
// （变更/终止孤儿行由 cleanup 兜底扫除）。

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

test('合同深化：详情聚合 tabs → 金额变更（留痕+联动）→ 预付款台账 → 追值', async ({ page, request }) => {
  const headers = await apiLogin(request)
  const contractNo = `HT-F${RUN}`

  // ---- 备数：项目 + 客户 + 销售合同 + 带预付款设备 ----
  const proj = await (await request.post(`${API}/projects`, {
    headers, data: { name: `E2E-变更-${RUN}` },
  })).json()
  const cust = await (await request.post(`${API}/customers`, {
    headers, data: { name: `客户-E2E-变更-${RUN}` },
  })).json()
  const contract = await (await request.post(`${API}/contracts`, {
    headers, data: { project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 1000000, contract_no: contractNo },
  })).json()
  expect(contract.id).toBeTruthy()
  const model = await (await request.post(`${API}/equipment-models`, {
    headers, data: { name: `E2E-型号-变更-${RUN}`, category: '大卡', gpu_count: 8 },
  })).json()
  const device = await (await request.post(`${API}/devices`, {
    headers, data: { project_id: proj.id, equipment_model_id: model.id, purchase_value: 960000, prepayment_amount: 12000, ownership: '表内自有' },
  })).json()

  // ---- UI：合同详情抽屉 → 聚合 tabs ----
  await uiLogin(page)
  await page.goto('/master/contracts')
  await page.getByPlaceholder('搜索...').fill(contractNo)
  const row = page.locator('.n-data-table-tr', { hasText: contractNo })
  await expect(row).toBeVisible()
  await row.getByTitle('详情').click()
  const drawer = page.locator('.n-drawer')
  await drawer.waitFor()
  for (const tab of ['发票', '计费单', '变更记录', '终止记录']) {
    await expect(drawer.locator('.n-tabs-tab', { hasText: tab })).toBeVisible()
  }

  // ---- 合同变更：金额 100万 → 120万（原因必填）----
  await drawer.getByRole('button', { name: '合同变更' }).click()
  const actionModal = page.locator('.n-modal').filter({ hasText: '合同变更' })
  await actionModal.waitFor()
  await actionModal.locator('.n-form-item', { hasText: '变更类型' }).locator('.n-base-selection').click()
  await page.locator('.n-base-select-option', { hasText: '金额变更' }).filter({ visible: true }).first().click()
  await actionModal.locator('.n-form-item', { hasText: '新合同金额' }).locator('input').fill('1200000')
  await actionModal.locator('.n-form-item', { hasText: '变更原因' }).locator('input').fill(`E2E变更-${RUN}`)
  await actionModal.getByRole('button', { name: '确认' }).click()
  await expect(page.locator('.n-message', { hasText: '变更已生效' })).toBeVisible({ timeout: 8000 })

  // 抽屉金额已更新 + 变更记录 tab 追值
  await expect(drawer.locator('.n-descriptions')).toContainText('1,200,000.00', { timeout: 8000 })
  await drawer.locator('.n-tabs-tab', { hasText: '变更记录' }).click()
  const activePane = drawer.locator('.n-tab-pane').filter({ visible: true })
  await expect(activePane).toContainText(`E2E变更-${RUN}`, { timeout: 8000 })
  await expect(activePane).toContainText('金额变更')

  // ---- 预付款台账页 ----
  await page.goto('/prepayments')
  await expect(page.getByRole('heading', { name: '预付款台账' })).toBeVisible()
  const ppRow = page.locator('.n-data-table-tr', { hasText: device.sn })
  await expect(ppRow).toBeVisible({ timeout: 8000 })
  await expect(ppRow).toContainText('12,000.00')  // 总额
  await expect(ppRow).toContainText('结转中')      // 未开始结转

  // ---- API 追值 ----
  const c2 = await (await request.get(`${API}/contracts/${contract.id}`, { headers })).json()
  expect(Number(c2.amount)).toBe(1200000)
  const amends = await (await request.get(`${API}/contracts/amendments`, {
    headers, params: { contract_id: contract.id },
  })).json()
  expect(amends.items.length).toBe(1)
  expect(Number(amends.items[0].before_json.amount)).toBe(1000000)   // DB NUMERIC(18,2) 回读带 .00，数值比
  expect(Number(amends.items[0].after_json.amount)).toBe(1200000)
  // EBS 出站（变更 sync_type=update）
  const logs = await (await request.get(`${API}/ebs/logs`, {
    headers, params: { entity_type: 'contract', limit: 50 },
  })).json()
  const mine = logs.items.filter((l: any) => l.entity_id === contract.id && l.sync_type === 'update')
  expect(mine.length, '变更应触发 EBS update 出站').toBeGreaterThanOrEqual(1)
  // 预付款余额单源
  const pp = await (await request.get(`${API}/prepayments/summary`, {
    headers, params: { project_id: proj.id },
  })).json()
  expect(pp.items.length).toBe(1)
  expect(pp.items[0].remaining).toBe(12000)
})
