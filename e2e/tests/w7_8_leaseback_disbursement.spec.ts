import { test, expect, type APIRequestContext, type Page, type Locator } from '@playwright/test'

// W7-8 端到端 3 场景（端到端铁律）：
//   ① 售后回租·回租出售全链路 —— UI 点「回租出售」按钮 → 资产切已处置 + 表外建档 + 预付款 settled
//   ② 放款阈值达成 —— 批次 threshold=50，推 1 台点亮（50%）→ 自动建金租申请（后端 hook）；推第 2 台不二建（哨兵幂等）
//   ③ 融资分类三字段 —— UI 录入 leasing_mode/financing_type/materials → 详情抽屉回显
// 共享 dev 库无测试隔离：每场景用唯一 SN/项目名/金额隔离自身数据。

const API = '/api'
const RUN = Date.now().toString(36)

// ---- 登录 ----
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

// ---- naive-ui n-select 三坑收敛助手（镜像 devices.spec.ts：placeholder 不在 input / 残留隐藏 option / 过渡动画时序）----
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
async function selectFirstOption(scope: Locator, label: string, page: Page): Promise<void> {
  await selectByLabel(scope, label).click()
  await waitForMenu(page, true)
  await page.waitForTimeout(280)
  const opt = page.locator('.n-base-select-option').filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await waitForMenu(page, false)
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
// filterable 下拉 + 候选可能很长（共享 dev 库累积的项目/供应商）：先在 input 里键入文本收窄，
// 再选唯一可见项。否则目标 option 虽在 DOM 但被下拉 max-height 滚出视口，filter(visible) 抓不到。
async function selectFilterableByText(scope: Locator, label: string, text: string, page: Page): Promise<void> {
  const sel = selectByLabel(scope, label)
  await sel.click()
  await waitForMenu(page, true)
  await page.waitForTimeout(280)
  await sel.locator('input').fill(text)
  await page.waitForTimeout(250)           // 等 naive-ui 过滤收窄
  const opt = page.locator('.n-base-select-option').filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await waitForMenu(page, false)
}
// 点按钮后等一条「新的」含 text 的 n-message 出现（count 增量，非 .last()：旧 message 退出有过渡残留）。
async function clickAndExpectMessage(scope: Locator, buttonName: string, page: Page, text: string): Promise<void> {
  const before = await page.locator('.n-message', { hasText: text }).count()
  await scope.getByRole('button', { name: buttonName }).click()
  await expect.poll(
    async () => page.locator('.n-message', { hasText: text }).count(),
    { timeout: 6000 },
  ).toBeGreaterThan(before)
}

// ---- API 推进单台设备到点亮验收（7 节点 × 进行中+已完成；点亮传 actual_date 激活起折旧/运营）----
const STAGES = ['订货', '在途', '到货', '己方压测', '上架', '客户压测', '点亮验收'] as const
async function advanceToLit(request: APIRequestContext, headers: Record<string, string>,
                            deviceId: string, lightOnDate: string): Promise<void> {
  for (const stage of STAGES) {
    for (const status of ['进行中', '已完成'] as const) {
      const body: Record<string, unknown> = { stage, status }
      if (stage === '点亮验收' && status === '已完成') body.actual_date = lightOnDate
      const r = await request.post(`${API}/devices/${deviceId}/stage`, { headers, data: body })
      expect(r.ok(), `advance ${stage}/${status}: ${await r.text()}`).toBeTruthy()
    }
  }
}

// ============ ① 回租出售全链路（UI 点按钮） ============
test('① 售后回租·回租出售：UI 点按钮 → 资产切已处置 + 表外(售后回租) + 预付款 settled', async ({ page, request }) => {
  test.slow() // 14 轮 API 推进 + 共享 dev 库设备列表膨胀 → 表格渲染慢，给 3 倍预算
  const headers = await apiLogin(request)
  const sn = `GPU-W78-LB-${RUN}`
  // 备数：项目 / 型号 / 资金供应商(is_leasing_org=true) / 售后回租设备(采购原值 96 万)
  const proj = await (await request.post(`${API}/projects`, { headers, data: { name: `E2E-回租-${RUN}` } })).json()
  const eq = await (await request.post(`${API}/equipment-models`, {
    headers, data: { name: `H100-LB-${RUN}`, category: '大卡', gpu_count: 8 },
  })).json()
  const funder = await (await request.post(`${API}/suppliers`, {
    headers, data: { name: `金租-LB-${RUN}`, type: '资金供应商', is_leasing_org: true },
  })).json()
  const dev = await (await request.post(`${API}/devices`, {
    headers, data: { sn, project_id: proj.id, equipment_model_id: eq.id, leasing_mode: '售后回租', purchase_value: 960000 },
  })).json()
  await advanceToLit(request, headers, dev.id, '2026-01-15')   // 上架派生表内自有+建卡；点亮激活运营
  const proc = await (await request.post(`${API}/leasing/processes`, {
    headers, data: { project_id: proj.id, supplier_id: funder.id, total_amount: 950000,
      leasing_mode: '售后回租', financing_type: '金租回租' },
  })).json()

  // UI：定位设备行 → 点「回租出售」
  await uiLogin(page)
  await page.goto('/devices')
  await expect(page.getByRole('heading', { name: '设备清单' })).toBeVisible()
  const row = page.locator('.n-data-table tbody tr').filter({ hasText: sn })
  await row.scrollIntoViewIfNeeded()
  await row.getByRole('button', { name: '回租出售' }).click()

  // 出售日预填今日、出售价预填采购原值 → 只选 金租机构 + 关联融资申请，确认出售
  const modal = page.locator('.n-modal').filter({ hasText: '回租出售' })
  await modal.waitFor()
  await selectFirstOption(modal, '金租机构', page)
  await selectFirstOption(modal, '关联融资申请', page)
  await clickAndExpectMessage(modal, '确认出售', page, '回租出售完成')

  // UI 信号：按钮翻成「已出售」tag（prepayment_settled=true 后不再显示出售按钮）
  await expect(row).toContainText('已出售')

  // API 真值断言（追值法：每跳核对）：off_balance 建档 售后回租 + 设备 prepayment_settled=true
  const reg = await (await request.get(`${API}/devices/off-balance-registers`, {
    headers, params: { device_id: dev.id },
  })).json()
  expect(reg.items.some((r: { register_type: string }) => r.register_type === '售后回租'),
    '回租出售应建档 表外(售后回租)').toBeTruthy()
  const devs = (await (await request.get(`${API}/devices`, { headers, params: { project_id: proj.id } })).json()).items
  const devAfter = devs.find((d: { id: string }) => d.id === dev.id)
  expect(devAfter.prepayment_settled, '回租出售后 prepayment_settled 应置 true').toBe(true)
  expect(proc.id).toBeTruthy()
})

// ============ ② 放款阈值达成（后端 hook，HTTP 端到端）============
test('② 放款阈值达成：批次 threshold=50，推 1 台点亮(50%)自动建金租申请；推第 2 台不二建', async ({ request, page }) => {
  const headers = await apiLogin(request)
  const proj = await (await request.post(`${API}/projects`, {
    headers, data: { name: `E2E-放款-${RUN}`, leasing_mode: '直租' },
  })).json()
  const eq = await (await request.post(`${API}/equipment-models`, {
    headers, data: { name: `H100-DIS-${RUN}`, category: '大卡', gpu_count: 8 },
  })).json()
  // 资金供应商 is_leasing_org=true：放款解析器 option② 按 is_leasing_org 找金租机构
  await (await request.post(`${API}/suppliers`, {
    headers, data: { name: `金租-DIS-${RUN}`, type: '资金供应商', is_leasing_org: true },
  })).json()

  // 批次订单 threshold=50（W7-8 决策 2：可配阈值）
  const order = await (await request.post(`${API}/orders`, {
    headers, data: { project_id: proj.id, equipment_model_id: eq.id, quantity: 2, unit_price: 960000,
      is_batch: true, disbursement_threshold_pct: 50 },
  })).json()
  expect(Number(order.disbursement_threshold_pct), '阈值应真写入 50').toBe(50)
  expect(order.disbursement_todo_process_id, '哨兵初始应为空').toBeNull()

  // 2 台直租设备挂入批次
  const mk = async () => (await request.post(`${API}/devices`, {
    headers, data: { project_id: proj.id, equipment_model_id: eq.id, leasing_mode: '直租', purchase_value: 960000 },
  })).json()
  const dev1 = await mk(); const dev2 = await mk()
  for (const id of [dev1.id, dev2.id]) {
    const r = await request.post(`${API}/devices/batch-assign`, { headers, data: { device_id: id, batch_id: order.id } })
    expect(r.ok(), `batch-assign ${id}: ${await r.text()}`).toBeTruthy()
  }

  const procsOf = async () => (await (await request.get(`${API}/leasing/processes`, {
    headers, params: { project_id: proj.id },
  })).json()).items

  // 推 dev1 点亮 → 1/2=50% 达阈值 → 自动建 leasing_process（直租→金租直租）
  await advanceToLit(request, headers, dev1.id, '2026-01-15')
  const procs1 = await procsOf()
  expect(procs1.length, 'dev1 点亮达阈值应自动建 1 条金租申请').toBe(1)
  expect(procs1[0].financing_type, 'financing_type 按 proj.leasing_mode=直租 派生').toBe('金租直租')
  expect(Number(procs1[0].total_amount), 'total_amount = Σ 批内 2 台 purchase_value').toBe(1920000)
  const orderAfter = await (await request.get(`${API}/orders/${order.id}`, { headers })).json()
  expect(orderAfter.disbursement_todo_process_id, '哨兵应写入').not.toBeNull()

  // 推 dev2 点亮 → 哨兵已设 → 不二建（幂等）
  await advanceToLit(request, headers, dev2.id, '2026-01-15')
  const procs2 = await procsOf()
  expect(procs2.length, '哨兵幂等：推第 2 台不应二建').toBe(1)

  // UI 可见性（端到端铁律）：金租页渲染 + 自动建的申请出现在真实表格
  await uiLogin(page)
  await page.goto('/leasing')
  await expect(page.getByRole('heading', { name: '金租流程' })).toBeVisible()
  await expect(page.locator('.n-data-table')).toContainText('1,920,000.00')
})

// ============ ③ 融资分类三字段（UI 录入 + 详情回显）============
test('③ 融资分类：UI 录入 leasing_mode/financing_type/materials → 详情抽屉三字段回显', async ({ page, request }) => {
  const headers = await apiLogin(request)
  const projName = `E2E-分类-${RUN}`
  const funderName = `金租-CLS-${RUN}`
  // 申请额跨 RUN 唯一：processCols 行内无项目/金租公司名，申请额是行内唯一可定位数据。
  // 固定 1234567 会撞共享 dev 库历次跑 ③ 留下的旧行（strict 违规：resolved to N elements）。
  const amountNum = 1_000_000 + (parseInt(RUN, 36) % 700_000)        // 1,000,000–1,699,999，跨 RUN 唯一
  const amountStr = String(amountNum)
  const amountFmt = amountNum.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  await (await request.post(`${API}/projects`, { headers, data: { name: projName } })).json()
  await (await request.post(`${API}/suppliers`, {
    headers, data: { name: funderName, type: '资金供应商', is_leasing_org: true },
  })).json()

  await uiLogin(page)
  await page.goto('/leasing')
  await page.getByRole('button', { name: '新建金租申请' }).click()
  const modal = page.locator('.n-modal').filter({ hasText: '新建金租申请' })
  await modal.waitFor()

  await selectFilterableByText(modal, '项目', projName, page)
  await selectFilterableByText(modal, '金租公司', funderName, page)
  await modal.locator('.n-form-item', { hasText: '申请金额' }).locator('input').fill(amountStr)
  await selectOptionByText(modal, '金租模式', '售后回租', page)
  await selectOptionByText(modal, '融资类型', '金租回租', page)
  await modal.locator('.n-form-item', { hasText: '材料备注' }).locator('input').fill('合同+发票+权属证明')
  await clickAndExpectMessage(modal, '创建', page, '金租申请已创建')

  // 按唯一申请额定位新建的申请行 → 详情抽屉回显三字段
  const row = page.locator('.n-data-table tbody tr').filter({ hasText: amountFmt })
  await row.getByRole('button', { name: '详情' }).click()
  const drawer = page.locator('.n-drawer-content')
  await expect(drawer).toContainText('模式：售后回租')
  await expect(drawer).toContainText('融资：金租回租')
  await expect(drawer).toContainText('合同+发票+权属证明')
})
