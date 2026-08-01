import { test, expect, type Page, type APIRequestContext } from '@playwright/test'

// 向导式工作台全链路 e2e：
//   a. 首页待办按角色过滤（采购/财务各验一次）
//   b. 待办「立即处理」→ 工作台：18 节点、当前步骤高亮、时间线文字状态
//   c. 抽屉办理资金入金 → 步骤自动推进
//   d. 刷新进度按钮、跳过弹窗（必填原因）、权限显隐（FINANCE_DIRECTOR vs 普通角色）
//   e. 跳转类步骤「立即处理」跳到真实页面（无「未配置该模块」）
// 串行执行：后续测试依赖前面测试推进的工作流状态。
test.describe.configure({ mode: 'serial' })

const api = '/api'
// 每次运行用时间戳保证项目名唯一，抗历史数据污染
const RUN = Date.now().toString(36)
const projectName = `E2E-向导-${RUN}`

let projectId = ''
let cfoHeaders: Record<string, string>

// API 登录拿 token（数据准备走 API，断言走真实浏览器 UI）
async function apiLogin(request: APIRequestContext, username: string, password = 'sie123') {
  const res = await request.post(`${api}/auth/login`, { form: { username, password } })
  expect(res.ok(), `API 登录失败: ${username}`).toBeTruthy()
  const { access_token } = await res.json()
  return { Authorization: `Bearer ${access_token}` }
}

// 真实浏览器 UI 登录（先清掉上一个账号的 localStorage token）
async function uiLogin(page: Page, username: string, password = 'sie123') {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/, { timeout: 8000 })
}

// 待办卡片定位（首页「待处理」卡片，没有待办时该卡片不渲染）
const todoCard = (page: Page) => page.locator('.n-card', { hasText: '待处理' })

test('准备数据：API 建主数据 + 项目（自动生成 18 步工作流）', async ({ request }) => {
  cfoHeaders = await apiLogin(request, 'cfo')

  // 主数据：供应商 / 客户 / 设备型号
  const sup = await request.post(`${api}/suppliers`, {
    headers: cfoHeaders, data: { name: `E2E供应商-${RUN}`, type: '设备供应商' },
  })
  expect(sup.ok()).toBeTruthy()
  const cus = await request.post(`${api}/customers`, {
    headers: cfoHeaders, data: { name: `E2E客户-${RUN}` },
  })
  expect(cus.ok()).toBeTruthy()
  const eq = await request.post(`${api}/equipment-models`, {
    headers: cfoHeaders, data: { name: `E2E-RTX5090-${RUN}`, category: '大卡', gpu_count: 8 },
  })
  expect(eq.ok()).toBeTruthy()
  const supplierId = (await sup.json()).id
  const customerId = (await cus.json()).id
  const equipId = (await eq.json()).id

  // 建项目 → 后端自动创建向导式工作流（Step 1 自动完成，当前 Step 2 销售合同/采购角色）
  const proj = await request.post(`${api}/projects`, {
    headers: cfoHeaders, data: { name: projectName },
  })
  expect(proj.ok()).toBeTruthy()
  projectId = (await proj.json()).id
  expect(projectId).toBeTruthy()

  const wfRes = await request.get(`${api}/workflows/${projectId}`, { headers: cfoHeaders })
  expect(wfRes.ok()).toBeTruthy()
  const wf = await wfRes.json()
  expect(wf.steps.length).toBe(18)
  expect(wf.current_step).toBe(2)

  // 把主数据 id 存下来供后续测试推进流程用
  ;(globalThis as any).__wiz = { supplierId, customerId, equipId }
})

test('a1. 采购账号：首页待办卡片可见且角色匹配', async ({ page }) => {
  await uiLogin(page, 'buyer')
  const card = todoCard(page)
  await expect(card).toBeVisible()
  await expect(card).toContainText(projectName)
  await expect(card).toContainText('Step 2 — 销售合同')
  await expect(card).toContainText('采购对接人')
})

test('a2. 财务账号：看不到采购角色的待办（角色过滤生效）', async ({ page }) => {
  await uiLogin(page, 'finance')
  // 财务专员的待办里不应出现这个项目（当前步骤 doer 是采购对接人）
  const card = todoCard(page)
  if (await card.count()) {
    await expect(card).not.toContainText(projectName)
  }
})

test('b. 待办「立即处理」→ 工作台：进度条 / 当前步骤高亮 / 时间线状态', async ({ page }) => {
  await uiLogin(page, 'buyer')
  // 从待办卡片进入工作台（每行的 router-link href 指向该项目 workspace，最精确）
  await expect(todoCard(page)).toContainText(projectName)
  await todoCard(page).locator(`a[href*="${projectId}"]`).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/workspace`))

  // 进度条：Step 1 已自动完成 → 1/18 ≈ 6%
  await expect(page.getByText('1 / 18 步完成')).toBeVisible()
  await expect(page.getByText('6%')).toBeVisible()

  // 当前步骤卡片高亮
  const current = page.locator('.n-card', { hasText: '当前' })
  await expect(current).toContainText('Step 2 — 销售合同')

  // 时间线文字状态：1 个已完成 + 1 个进行中 + 16 个待处理
  await expect(page.locator('.n-tag', { hasText: '已完成' })).toHaveCount(1)
  await expect(page.locator('.n-tag', { hasText: '进行中' })).toHaveCount(1)
  await expect(page.locator('.n-tag', { hasText: '待处理' })).toHaveCount(16)
})

test('e. 跳转类步骤「立即处理」跳到真实页面（无「未配置该模块」）', async ({ page }) => {
  await uiLogin(page, 'buyer')
  await page.goto(`/projects/${projectId}/workspace`)
  await expect(page.getByText('Step 2 — 销售合同')).toBeVisible()
  await page.getByRole('button', { name: '立即处理' }).click()
  // 销售合同 module=contract → /master/contracts（携带 project_id 预填）
  await expect(page).toHaveURL(new RegExp(`/master/contracts\\?project_id=${projectId}`))
  await expect(page.getByText('未配置该模块')).toHaveCount(0)
})

test('c. 抽屉办理资金入金 → 步骤自动推进', async ({ page, request }) => {
  // —— API 推进到 Step 6（银行流贷入金 / FINANCE_STAFF / capital_in 抽屉） ——
  const { supplierId, customerId, equipId } = (globalThis as any).__wiz
  const post = (url: string, data: Record<string, unknown>) =>
    request.post(`${api}${url}`, { headers: cfoHeaders, data })

  // Step 2 销售合同 / Step 3 采购合同
  const sc = await post('/contracts', {
    project_id: projectId, type: 'SALES', party_id: customerId,
    amount: 5_000_000, monthly_rent: 200_000,
    start_date: '2026-01-01', end_date: '2028-12-31',
  })
  expect(sc.ok()).toBeTruthy()
  const salesContractId = (await sc.json()).id
  const pc = await post('/contracts', {
    project_id: projectId, type: 'PURCHASE', party_id: supplierId,
    amount: 4_000_000, start_date: '2026-01-01', end_date: '2026-12-31',
  })
  expect(pc.ok()).toBeTruthy()
  const purchaseContractId = (await pc.json()).id

  // Step 4 销售订单 / Step 5 采购订单
  expect((await post('/sales-orders', {
    project_id: projectId, contract_id: salesContractId, equipment_model_id: equipId,
    quantity: 10, monthly_rent_per_unit: 20_000, total_monthly_rent: 200_000,
    start_date: '2026-01-01', end_date: '2028-12-31',
  })).ok()).toBeTruthy()
  expect((await post('/orders', {
    project_id: projectId, contract_id: purchaseContractId, equipment_model_id: equipId,
    quantity: 10, unit_price: 400_000,
  })).ok()).toBeTruthy()

  // 刷新进度 → 当前步骤应为 Step 6 银行流贷入金
  const refRes = await request.post(`${api}/workflows/${projectId}/refresh`, { headers: cfoHeaders })
  expect(refRes.ok()).toBeTruthy()
  expect((await refRes.json()).current_step).toBe(6)

  // —— UI：财务专员从待办进工作台，抽屉提交一笔入金 ——
  await uiLogin(page, 'finance')
  const card = todoCard(page)
  await expect(card).toContainText(projectName)
  await expect(card).toContainText('Step 6 — 银行流贷入金')
  await card.locator(`a[href*="${projectId}"]`).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/workspace`))

  // 当前步骤卡片 + 进度（1~5 已完成 → 5/18 ≈ 28%）
  await expect(page.getByText('5 / 18 步完成')).toBeVisible()
  const current = page.locator('.n-card', { hasText: '当前' })
  await expect(current).toContainText('Step 6 — 银行流贷入金')

  // 打开抽屉，提交入金（来源类型已由 prefill 锁定为银行流贷，日期默认今天）
  await current.getByRole('button', { name: '立即处理' }).click()
  const drawer = page.locator('.n-drawer')
  await expect(drawer).toBeVisible()
  await expect(drawer).toContainText('Step 6 — 银行流贷入金')
  await drawer.locator('input[placeholder="金额（元）"]').fill('2000000')
  await drawer.getByRole('button', { name: '确认入金' }).click()

  // 抽屉关闭 + 步骤自动推进到 Step 7（自有资金入金），进度 6/18
  await expect(drawer).toBeHidden({ timeout: 8000 })
  await expect(page.getByText('6 / 18 步完成')).toBeVisible()
  await expect(page.locator('.n-card', { hasText: '当前' })).toContainText('Step 7 — 自有资金入金')
})

test('d1. 权限显隐：普通角色看不到必做步骤的跳过/标记完成，刷新进度可用', async ({ page }) => {
  await uiLogin(page, 'finance')
  await page.goto(`/projects/${projectId}/workspace`)
  const current = page.locator('.n-card', { hasText: '当前' })
  await expect(current).toContainText('Step 7 — 自有资金入金')

  // Step 7 为必做步骤 + 财务专员非管理角色 → 两个按钮都不渲染
  await expect(current.getByRole('button', { name: '标记完成' })).toHaveCount(0)
  await expect(current.getByRole('button', { name: '跳过' })).toHaveCount(0)

  // 「刷新进度」按钮可用
  await page.getByRole('button', { name: '刷新进度' }).click()
  await expect(page.getByText('进度已刷新')).toBeVisible()
})

test('d2. 权限显隐 + 跳过弹窗：FINANCE_DIRECTOR 可见，原因必填', async ({ page }) => {
  await uiLogin(page, 'cfo')
  await page.goto(`/projects/${projectId}/workspace`)
  const current = page.locator('.n-card', { hasText: '当前' })
  await expect(current).toContainText('Step 7 — 自有资金入金')

  // 财务总监（FINANCE_DIRECTOR）两个按钮都可见
  await expect(current.getByRole('button', { name: '标记完成' })).toBeVisible()
  await expect(current.getByRole('button', { name: '跳过' })).toBeVisible()

  // 跳过弹窗：不填原因 → 提示必填且弹窗不关闭
  await current.getByRole('button', { name: '跳过' }).click()
  const dialog = page.locator('.n-modal')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('该步骤为必做步骤')
  await dialog.getByRole('button', { name: '确认跳过' }).click()
  await expect(page.getByText('请填写跳过原因')).toBeVisible()
  await expect(dialog).toBeVisible()

  // 填原因 → 跳过成功，步骤推进到 Step 8，时间线出现「已跳过」
  await dialog.locator('textarea[placeholder="跳过原因（必填）"]').fill('自有资金已足额，无需入金（e2e）')
  await dialog.getByRole('button', { name: '确认跳过' }).click()
  await expect(page.getByText('步骤 7 已跳过')).toBeVisible()
  await expect(page.locator('.n-card', { hasText: '当前' })).toContainText('Step 8 — 预付采购款')
  await expect(page.locator('.n-tag', { hasText: '已跳过' })).toHaveCount(1)
})
