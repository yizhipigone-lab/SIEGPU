import { test, expect, APIRequestContext, Locator, Page } from '@playwright/test'

// 一期 W5-6 端到端：按台计费全链路 + 两个守门（M-1 防双计 / 点亮返工守门）。
//
// 策略：新设备/推进/计费用 API（request fixture）确定性 seed，只把「新 UI 面」（按台计费 modal）
// 留给浏览器驱动；守门是后端逻辑、UI 只以错误 toast 呈现（脆），故守门走 HTTP 全栈断言。
// 断言落在「持久表格行」而非「瞬时 toast」：success toast ~3s 自动消失，行才是 durable 信号。

const BASE = 'http://localhost:8080'
const API = `${BASE}/api`
const STAGES = ['订货', '在途', '到货', '己方压测', '上架', '客户压测', '点亮验收']

// ---- naive-ui n-select 三坑助手（从 devices.spec.ts 镜像；那边未 export，此处内联保持自洽）----
async function waitForMenu(page: Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}
function selectByLabel(scope: Page | Locator, label: string): Locator {
  // 精确匹配 label 文本节点再回到所属 form-item 的 selection：
  // BillingsView 里「项目（用于筛选设备）」含子串「设备」，子串匹配会撞两个 form-item（strict mode 报错）。
  return scope.getByText(label, { exact: true })
    .locator('xpath=ancestor::div[contains(@class, "n-form-item")][1]')
    .locator('.n-base-selection')
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

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/)
}

// ---- API seed 助手 ----
async function apiLogin(request: APIRequestContext): Promise<string> {
  const r = await request.post(`${API}/auth/login`, { form: { username: 'cfo', password: 'sie123' } })
  expect(r.ok()).toBeTruthy()
  return (await r.json()).access_token
}

async function apiJson(request: APIRequestContext, token: string, method: string, path: string, body?: unknown) {
  const r = await request.fetch(`${API}${path}`, {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body ?? {},
  })
  let json: any = null
  try { json = await r.json() } catch { /* 204 等无体 */ }
  return { status: r.status(), body: json }
}

/** 建一台「表内自有」设备并推进到点亮验收（上架建卡 + 点亮激活）。点亮日定在本月 1 号 → 首月整月计费。 */
async function seedBillableDevice(request: APIRequestContext, token: string, sn: string,
                                   overrides: Record<string, unknown> = {}): Promise<{id: string, sn: string, projectName: string}> {
  const auth = { Authorization: `Bearer ${token}` }
  const [pj, eq] = await Promise.all([
    request.get(`${API}/projects`, { headers: auth }).then(r => r.json()),
    request.get(`${API}/equipment-models`, { headers: auth }).then(r => r.json()),
  ])
  const proj = pj.items[0], equip = eq.items[0]
  const created = await apiJson(request, token, 'POST', '/devices', {
    sn, project_id: proj.id, equipment_model_id: equip.id,
    ownership: '表内自有', leasing_mode: '自有',
    purchase_value: '100000', monthly_price: '10000', ...overrides,
  })
  expect(created.status).toBe(201)
  const devId = created.body.id
  // 用本地日期分量拼 YYYY-MM-DD，避免 toISOString 的 UTC 偏移在零点~早8点把「本月1号」推回上月末（首月按日比例计费会因此变成零头）。
  const firstOfMonth = new Date(); firstOfMonth.setDate(1)
  const lightOn = `${firstOfMonth.getFullYear()}-${String(firstOfMonth.getMonth() + 1).padStart(2, '0')}-${String(firstOfMonth.getDate()).padStart(2, '0')}`
  for (const stage of STAGES) {
    for (const status of ['进行中', '已完成'] as const) {
      const actual = (stage === '点亮验收' && status === '已完成') ? lightOn : undefined
      const r = await apiJson(request, token, 'POST', `/devices/${devId}/stage`, { stage, status, actual_date: actual })
      expect(r.status, `advance ${stage}/${status}: ${JSON.stringify(r.body)}`).toBe(200)
    }
  }
  return { id: devId, sn, projectName: proj.name }
}

// ============ ① 按台全链路（浏览器驱动新 modal）============
test.describe.serial('W5-6 按台计费', () => {
  test('① 按台计费 modal：金额取 device.monthly_price，设备列回填、订单空安全', async ({ page, request }) => {
    const token = await apiLogin(request)
    const sn = `GPU-E2E-W56-${Date.now()}`
    const dev = await seedBillableDevice(request, token, sn)

    await login(page)
    await page.goto('/billing')
    await page.getByRole('button', { name: '按台计费' }).click()
    const modal = page.locator('.n-modal')
    await modal.waitFor()

    // 选项目（收窄设备列表）→ 选设备（按唯一 SN）→ 选第一个销售合同
    await selectOptionByText(modal, '项目（用于筛选设备）', dev.projectName, page)
    await selectOptionByText(modal, '设备', sn, page)
    await selectByLabel(modal, '销售合同').click()
    await waitForMenu(page, true); await page.waitForTimeout(280)
    await page.locator('.n-base-select-option').filter({ visible: true }).first().click()
    await waitForMenu(page, false)

    await modal.getByRole('textbox', { name: '请输入' }).fill('1')        // 计费期数 = 1
    // 计费日期默认今天，保持不变
    await modal.getByRole('button', { name: '生成', exact: true }).click()

    // 断言落在持久表格行：设备 SN 回填、订单空安全(-)、金额=10,000.00（首月整月=monthly_price）
    const row = page.locator('.n-data-table tbody tr', { hasText: sn })
    await expect(row).toBeVisible({ timeout: 8000 })
    await expect(row).toContainText('10,000.00')
    // 同行的订单列应为「-」（按台计费无订单），证明 order_id 空安全渲染不崩
    const orderCell = row.locator('td').nth(2)
    await expect(orderCell).toHaveText('-')
  })

  // ============ ③ M-1 防双计（HTTP 全栈）============
  test('③ M-1：单台订单挂设备后旧 light_on 返 FLOW_TYPE_DEVICE', async ({ request }) => {
    const token = await apiLogin(request)
    const orders = await request.get(`${API}/orders`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json())
    const order = orders.items[0]
    const sn = `GPU-E2E-M1-${Date.now()}`
    // 单台订单挂一台设备（order_id 分支）→ resolve_flow_type 翻 "device"
    const dev = await apiJson(request, token, 'POST', '/devices', {
      sn, project_id: (await request.get(`${API}/projects`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json())).items[0].id,
      equipment_model_id: (await request.get(`${API}/equipment-models`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json())).items[0].id,
      order_id: order.id, ownership: '表内自有', leasing_mode: '自有',
      purchase_value: '50000', monthly_price: '5000',
    })
    expect(dev.status).toBe(201)
    const today = new Date().toISOString().slice(0, 10)
    const r = await apiJson(request, token, 'POST', `/orders/${order.id}/light-on`, { actual_date: today })
    expect(r.status).toBe(409)
    expect(r.body.detail.code).toBe('FLOW_TYPE_DEVICE')
  })

  // ============ ④ 点亮返工守门（HTTP 全栈）============
  test('④ 已建卡+计费的点亮设备返工被拦（先红冲按台计费与处置资产）', async ({ request }) => {
    const token = await apiLogin(request)
    const sn = `GPU-E2E-REWORK-${Date.now()}`
    const dev = await seedBillableDevice(request, token, sn)
    // 先按台计费一期（让设备既有运营中资产、又有 billing）
    const sales = (await request.get(`${API}/contracts`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()))
      .items.find((c: any) => c.type === 'SALES')
    const bill = await apiJson(request, token, 'POST', '/billings/device', {
      device_id: dev.id, contract_id: sales.id, period_index: 1,
      billing_date: new Date().toISOString().slice(0, 10), idempotency_key: `${dev.id}-1`,
    })
    expect(bill.status).toBe(201)
    // 点亮验收 已完成 → 不合格：应被 D5 守卫拦
    const r = await apiJson(request, token, 'POST', `/devices/${dev.id}/stage`, { stage: '点亮验收', status: '不合格' })
    expect(r.status).toBe(409)
    expect(r.body.detail.code).toBe('STATE_ERROR')
  })

  // ============ ② 双轨回归（HTTP 全栈）：旧订单维度 generate_billing 仍按 contract.monthly_rent ============
  test('② 双轨回归：seed 全新 legacy 订单 + light-on + generate_billing，device_id 空、金额>0', async ({ request }) => {
    const token = await apiLogin(request)
    const auth = { Authorization: `Bearer ${token}` }
    const [pj, eq, contracts] = await Promise.all([
      request.get(`${API}/projects`, { headers: auth }).then(r => r.json()),
      request.get(`${API}/equipment-models`, { headers: auth }).then(r => r.json()),
      request.get(`${API}/contracts`, { headers: auth }).then(r => r.json()),
    ])
    // 去条件化（W5-6 审计）：显式选 monthly_rent>0 的 SALES 合同（legacy 金额来源）；不再用
    // orders[length-1] + if/else——原实现可能选中已翻 device 的订单走 else 直接 PASS（假绿，没真测 legacy）。
    const sales = contracts.items.find((c: any) => c.type === 'SALES' && Number(c.monthly_rent) > 0)
    expect(sales, '应至少存在一个 monthly_rent>0 的 SALES 合同供 legacy 回归').toBeTruthy()
    // seed 全新非批量订单（未挂设备 → assert_legacy_path 放行 legacy 路径，确定性消除 device 翻转风险）
    const order = await apiJson(request, token, 'POST', '/orders', {
      project_id: pj.items[0].id, equipment_model_id: eq.items[0].id,
      quantity: 3, unit_price: '50000',
    })
    expect(order.status).toBe(201)
    // light-on：建 quantity=3 单张资产 + 起折旧，给 generate_billing 提供 light_on 日期
    const lightOnDate = new Date().toISOString().slice(0, 10)
    const lit = await apiJson(request, token, 'POST', `/orders/${order.body.id}/light-on`, { actual_date: lightOnDate })
    expect(lit.status, `light-on: ${JSON.stringify(lit.body)}`).toBe(200)
    // legacy generate_billing：金额来自 contract.monthly_rent，device_id 必空（双轨与按台计费互不干扰）
    const period = 999  // 几乎不会被占用的期数，避免与历史数据撞车
    const r = await apiJson(request, token, 'POST', '/billings', {
      order_id: order.body.id, contract_id: sales.id, period_index: period,
      billing_date: lightOnDate, idempotency_key: `${order.body.id}-${period}`,
    })
    expect(r.status, `generate_billing: ${JSON.stringify(r.body)}`).toBe(201)
    expect(r.body.device_id).toBeNull()
    expect(Number(r.body.amount)).toBeGreaterThan(0)
  })
})
