import { test, expect, type APIRequestContext, type Page, type Locator } from '@playwright/test'

// 二期 W3-4 收入核算路径判定 —— 合同表单端到端（端到端铁律）：
//   UI 建销售合同（项目=经营租赁/自有）→ 表单实时预览 R1「经营租赁」→ 保存即自动判定
//   → 列表「核算路径」列可见 → 详情判定区（依据/留痕）→ 人工覆盖为净额法（原因必填）
//   → API 追值法断言：合同快照 + EBS 出站日志（contract_revenue_method，method_confirmed=true）
// 共享 dev 库无隔离：项目 `E2E-` 前缀、客户 `客户-E2E` 前缀、合同号 `HT-F` 前缀，
// 由 globalTeardown → cleanup_e2e 清理（见 backend/app/scripts/cleanup_e2e.py）。

const API = '/api'
const RUN = Date.now().toString(36)

// ---- 登录（镜像 ebs.spec.ts）----
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

// ---- naive-ui n-select 三坑收敛（镜像 ebs.spec.ts）----
async function waitForMenu(page: Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}
async function selectOptionByText(scope: Locator, label: string, text: string, page: Page): Promise<void> {
  await scope.locator('.n-form-item', { hasText: label }).locator('.n-base-selection').click()
  await waitForMenu(page, true)
  await page.waitForTimeout(280)
  const opt = page.locator('.n-base-select-option', { hasText: text }).filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await waitForMenu(page, false)
}
// 远程下拉专用（项目/对方）：选项是远程拉取 + 菜单虚拟滚动只渲染可见窗口，
// 全套并发慢库下「干等 option 渲染」不可靠 → 先键入文本收窄到唯一项再点（revenue-chain 同款手法）。
async function selectRemoteByText(scope: Locator, label: string, text: string, page: Page): Promise<void> {
  const sel = scope.locator('.n-form-item', { hasText: label }).locator('.n-base-selection')
  await sel.click()
  await waitForMenu(page, true)
  await sel.locator('input').fill(text)
  await page.waitForTimeout(400) // 等 naive-ui 过滤收窄
  const opt = page.locator('.n-base-select-option', { hasText: text }).filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible', timeout: 15000 })
  await opt.click()
  await waitForMenu(page, false)
}

test('收入判定：建合同预览 R1 → 保存自动判定 → 详情覆盖为净额法 → 追值断言', async ({ page, request }) => {
  const headers = await apiLogin(request)

  // 备数：经营租赁/自有项目 + 客户（真实枚举值，锁 D1）
  const projName = `E2E-判定-${RUN}`
  const custName = `客户-E2E-判定-${RUN}`
  const contractNo = `HT-F${RUN}`
  const proj = await (await request.post(`${API}/projects`, {
    headers, data: { name: projName, business_type: '经营租赁', leasing_mode: '自有' },
  })).json()
  expect(proj.id).toBeTruthy()
  const cust = await (await request.post(`${API}/customers`, { headers, data: { name: custName } })).json()
  expect(cust.id).toBeTruthy()

  // —— UI：合同页新增 ——
  await uiLogin(page)
  await page.goto('/master/contracts')
  await page.getByRole('button', { name: '新增' }).click()
  const modal = page.locator('.n-modal').filter({ hasText: '新增' })
  await modal.waitFor()

  await selectRemoteByText(modal, '项目', projName, page)
  // 四期 W4 新增「合同类型」字段 → hasText '类型' 会双命中（类型/合同类型），此处 label 精确匹配
  await modal.locator('.n-form-item')
    .filter({ has: page.getByText('类型', { exact: true }) })
    .locator('.n-base-selection').click()
  await waitForMenu(page, true)
  await page.waitForTimeout(280)
  const typeOpt = page.locator('.n-base-select-option', { hasText: '销售' }).filter({ visible: true }).first()
  await typeOpt.waitFor({ state: 'visible' })
  await typeOpt.click()
  await waitForMenu(page, false)
  // 实时预览：项目=经营租赁/自有 + 销售 → R1 经营租赁
  const preview = modal.getByTestId('judge-preview')
  await expect(preview, '选定项目+类型后应出现判定预览').toBeVisible({ timeout: 8000 })
  await expect(preview).toContainText('经营租赁')
  await expect(preview).toContainText('R1')

  await selectRemoteByText(modal, '对方', custName, page)
  await modal.locator('.n-form-item', { hasText: '合同金额' }).locator('input').fill('1000000')
  await modal.locator('.n-form-item', { hasText: '合同号' }).locator('input').fill(contractNo)
  await modal.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.n-message', { hasText: '已保存' })).toBeVisible({ timeout: 8000 })

  // —— 列表：核算路径列显示「经营租赁」（唯一锚点：搜索合同号，禁首行假设）——
  await page.getByPlaceholder('搜索...').fill(contractNo)
  const row = page.locator('.n-data-table-tr', { hasText: contractNo })
  await expect(row).toContainText('经营租赁')

  // —— 详情：判定区（依据 + 留痕）——
  await row.getByTitle('详情').click()
  const drawer = page.locator('.n-drawer')
  const judgeDetail = drawer.getByTestId('judge-detail')
  await expect(judgeDetail).toBeVisible()
  await expect(judgeDetail).toContainText('经营租赁')
  await expect(judgeDetail).toContainText('R1 命中')

  // —— 人工覆盖：净额法 + 原因（必填校验：先空原因确认被拦）——
  await drawer.getByRole('button', { name: '人工确认核算路径' }).click()
  const actionModal = page.locator('.n-modal').filter({ hasText: '人工确认核算路径' })
  await actionModal.waitFor()
  await selectOptionByText(actionModal, '核算路径', '净额法', page)
  await actionModal.getByRole('button', { name: '确认' }).click()
  await expect(page.locator('.n-message', { hasText: '请填写必填项' })).toBeVisible({ timeout: 6000 })
  await actionModal.locator('.n-form-item', { hasText: '原因' }).locator('input').fill(`实质代销-E2E-${RUN}`)
  await actionModal.getByRole('button', { name: '确认' }).click()
  await expect(page.locator('.n-message', { hasText: '已确认/覆盖' })).toBeVisible({ timeout: 8000 })

  // 详情区更新：净额法 + 已人工确认
  await expect(judgeDetail).toContainText('净额法', { timeout: 8000 })
  await expect(judgeDetail).toContainText('已人工确认')

  // —— 追值法（API 读回真值）——
  const list = await (await request.get(`${API}/contracts`, {
    headers, params: { project_id: proj.id },
  })).json()
  const mine = list.items.find((c: { contract_no: string }) => c.contract_no === contractNo)
  expect(mine, '应找到本次合同').toBeTruthy()
  expect(mine.revenue_method).toBe('净额法')
  expect(mine.method_judge_basis).toContain(`实质代销-E2E-${RUN}`)
  expect(mine.method_confirmed_at).toBeTruthy()

  // EBS 出站：判定快照日志（覆盖后 method_confirmed=true）
  const logs = await (await request.get(`${API}/ebs/logs`, {
    headers, params: { entity_type: 'contract_revenue_method', limit: 100 },
  })).json()
  const myLogs = logs.items.filter((l: { entity_id: string }) => l.entity_id === mine.id)
  expect(myLogs.length, '应有判定快照 EBS 日志').toBeGreaterThanOrEqual(1)
  const confirmed = myLogs.find((l: any) => l.request_payload?.method_confirmed === true)
  expect(confirmed, '应有一条人工确认后的快照日志').toBeTruthy()
  expect(confirmed.request_payload.revenue_method).toBe('净额法')
})
