import { test, expect, type APIRequestContext, type Page, type Locator } from '@playwright/test'

// 二期 W1-2 EBS 接口 Mock —— EbsMonitor.vue 端到端（端到端铁律）：
//   映射配置 CRUD（UI 新增 direct 映射）→ 手动触发出站（UI）→ 同步日志可见（UI）
//   → 映射转换真值断言（API 追值法：request_payload 含重命名 key、原 key 消失）
//   → 幂等（二次触发 skipped，不新增 log；UI 结果区显示「幂等跳过」）
// 共享 dev 库无隔离：客户名带 `客户-E2E` 前缀、映射 ebs_field 带 `E2E_` 前缀，
// 由 globalTeardown → cleanup_e2e 清理（见 backend/app/scripts/cleanup_e2e.py）。

const API = '/api'
const RUN = Date.now().toString(36)

// ---- 登录（镜像 w7_8_leaseback_disbursement.spec.ts）----
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

// ---- naive-ui n-select 三坑收敛（镜像 w7_8）----
async function waitForMenu(page: Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}
function selectByLabel(scope: Page | Locator, label: string): Locator {
  return scope.locator('.n-form-item', { hasText: label }).locator('.n-base-selection')
}
async function selectOptionByText(scope: Locator, label: string, text: string, page: Page): Promise<void> {
  await selectByLabel(scope, label).click()
  await waitForMenu(page, true)
  await page.waitForTimeout(280)
  const opt = page.locator('.n-base-select-option', { hasText: text }).filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await waitForMenu(page, false)
}
// 点按钮后等一条「新的」含 text 的 n-message（count 增量，避开退出过渡残留）。
async function clickAndExpectMessage(scope: Locator, buttonName: string, page: Page, text: string): Promise<void> {
  const before = await page.locator('.n-message', { hasText: text }).count()
  await scope.getByRole('button', { name: buttonName }).click()
  await expect.poll(
    async () => page.locator('.n-message', { hasText: text }).count(),
    { timeout: 6000 },
  ).toBeGreaterThan(before)
}

test('EBS 监控：映射配置新增 → 手动触发出站 → 日志可见 + 映射转换生效 + 幂等', async ({ page, request }) => {
  const headers = await apiLogin(request)

  // 防御性清理：dev 库可能残留 customer/name 映射（与本次新增同 siegpu_field 冲突 409）。
  // EBS 映射表为二期 Mock 期新表、seed 不建、无生产数据，清掉旧 customer/name 条目安全。
  const existMaps = await (await request.get(`${API}/ebs/mappings`, {
    headers, params: { entity_type: 'customer' },
  })).json()
  for (const m of existMaps.items || []) {
    if (m.siegpu_field === 'name') await request.delete(`${API}/ebs/mappings/${m.id}`, { headers })
  }

  const custName = `客户-E2E-EBS-${RUN}`
  const ebsField = `E2E_CNAME_${RUN}` // 映射目标字段，带 E2E_ 前缀供 cleanup 识别

  // 备一个客户（cleanup 按 `客户-E2E` 前缀清；同步日志按该客户 id 清）
  const cust = await (await request.post(`${API}/customers`, { headers, data: { name: custName } })).json()
  expect(cust.id).toBeTruthy()

  // —— UI：进 EBS 监控页 ——
  await uiLogin(page)
  await page.goto('/ebs')
  await expect(page.getByRole('heading', { name: 'EBS 同步监控' })).toBeVisible()

  // —— ① 新增 direct 映射 customer.name → E2E_CNAME_{RUN} ——
  await page.getByRole('button', { name: '新增映射' }).click()
  const modal = page.locator('.n-modal').filter({ hasText: '新增映射' })
  await modal.waitFor()
  await selectOptionByText(modal, '实体类型', '客户', page)
  await modal.locator('.n-form-item', { hasText: 'SIEGPU 字段' }).locator('input').fill('name')
  await modal.locator('.n-form-item', { hasText: 'EBS 字段' }).locator('input').fill(ebsField)
  await clickAndExpectMessage(modal, '新增', page, '已新增')

  // 映射出现在字段映射配置表
  const mappingTable = page.locator('.n-data-table').first()
  await expect(mappingTable).toContainText(ebsField)

  // —— ② 手动触发：实体类型=客户 + 实体 ID（粘 UUID）→ 同步 ——
  const triggerCard = page.locator('.n-card').filter({ hasText: '手动触发同步' })
  await selectOptionByText(triggerCard, '实体类型', '客户', page)
  await triggerCard.locator('.n-form-item', { hasText: '实体 ID' }).locator('input').fill(cust.id)
  await clickAndExpectMessage(triggerCard, '同步', page, '同步完成')

  // 同步日志表出现 MOCK_SUCCESS + EBS 回执
  const logsCard = page.locator('.n-card').filter({ hasText: '同步日志' })
  await expect(logsCard).toContainText('MOCK_SUCCESS')
  await expect(logsCard).toContainText('MOCK-EBS-')

  // —— ③ 追值法（API 读回真值）：映射转换生效 ——
  const logs1 = await (await request.get(`${API}/ebs/logs`, {
    headers, params: { entity_type: 'customer', limit: 50 },
  })).json()
  const mine1 = logs1.items.filter((l: { entity_id: string }) => l.entity_id === cust.id)
  expect(mine1.length, '应至少 1 条同步日志').toBeGreaterThanOrEqual(1)
  const first = mine1.find((l: { skipped: boolean }) => !l.skipped)!
  expect(first.status).toBe('MOCK_SUCCESS')
  // 重命名生效：EBS 字段名出现、SIEGPU 原字段名消失
  expect(first.request_payload[ebsField], '映射后载荷应含重命名的 EBS 字段').toBe(custName)
  expect('name' in first.request_payload, '原 SIEGPU 字段名应被映射消费掉').toBe(false)

  // —— ④ 幂等：二次触发 → skipped，不新增 log；UI 结果区显示「幂等跳过」——
  await clickAndExpectMessage(triggerCard, '同步', page, '同步完成')
  await expect(triggerCard).toContainText('幂等跳过')
  const logs2 = await (await request.get(`${API}/ebs/logs`, {
    headers, params: { entity_type: 'customer', limit: 50 },
  })).json()
  const mine2 = logs2.items.filter((l: { entity_id: string }) => l.entity_id === cust.id)
  expect(mine2.length, '幂等跳过不应新增 log').toBe(mine1.length)
})
