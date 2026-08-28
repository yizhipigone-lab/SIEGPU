import { test, expect, request as pwRequest, APIRequestContext } from '@playwright/test'

// S1-01（红→绿）：设备推进「在途」但所属采购订单尚无「已通过」的采购验收 →
// 前端必须展示后端具体原因（含"尚未通过采购验收"），而不是笼统的"可能状态机不允许该转换"。
// 旧前端 catch{} 吞错 → 断言失败（红）；修复后前端透传 errMsg → 通过（绿）。
// 造数：API 全链路（客户/型号/供应商/项目/销售合同/采购合同/批次订单/设备/批次挂载），sn 做行锚点。
const UID = Date.now().toString().slice(-6)

let ctx: APIRequestContext
let TOK = ''
const H = () => ({ Authorization: `Bearer ${TOK}` })

// naive-ui 下拉三坑（与 devices.spec.ts 同款收敛）：开/关需显式等待 + 过渡动画 280ms + 只点可见 option。
async function waitForMenu(page: import('@playwright/test').Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}

async function selectOptionByText(modal: import('@playwright/test').Locator, label: string, text: string, page: import('@playwright/test').Page): Promise<void> {
  await modal.locator('.n-form-item', { hasText: label }).locator('.n-base-selection').click()
  await waitForMenu(page, true)
  await page.waitForTimeout(280)
  const opt = page.locator('.n-base-select-option', { hasText: text }).filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await waitForMenu(page, false)
}

async function apiSeed(): Promise<string> {
  ctx = await pwRequest.newContext({ baseURL: 'http://localhost:8088' })
  const login = await ctx.post('/api/auth/login', { form: { username: 'admin', password: 'sie123' } })
  expect(login.ok()).toBeTruthy()
  TOK = (await login.json()).access_token
  const h = H()
  const post = async (path: string, data: any) => {
    const r = await ctx.post(path, { headers: h, data })
    expect(r.ok(), `${path} 应成功: ${r.status()}`).toBeTruthy()
    return r.json()
  }
  const cust = await post('/api/customers', { name: `S1客${UID}`, industry: '互联网' })
  const eq = await post('/api/equipment-models', { name: `S1型${UID}`, category: '大卡', gpu_type: 'X', gpu_count: 8 })
  const sup = await post('/api/suppliers', { name: `S1供${UID}`, type: '设备供应商' })
  const proj = await post('/api/projects', { name: `S1项${UID}`, customer_id: cust.id, business_type: '经营租赁', leasing_mode: '直租', total_investment: 500000 })
  const sc = await post('/api/contracts', { project_id: proj.id, type: 'SALES', biz_type: '算力租赁', party_id: cust.id, amount: 1000000, amount_incl_tax: 1130000, tax_rate: 0.13, lease_months: 36, contract_no: `S1XS${UID}` })
  const pc = await post('/api/contracts', { project_id: proj.id, type: 'PURCHASE', biz_type: '算力租赁', party_id: sup.id, amount: 442477.88, amount_incl_tax: 500000, tax_rate: 0.13, parent_contract_id: sc.id, contract_no: `S1CG${UID}` })
  const po = await post('/api/orders', { project_id: proj.id, contract_id: pc.id, equipment_model_id: eq.id, quantity: 1, unit_price: 442477.88, is_batch: true, batch_name: `S1批次${UID}` })
  const dev = await post('/api/devices', { project_id: proj.id, equipment_model_id: eq.id, order_id: po.id, monthly_price: 8333.33, purchase_value: 442477.88, leasing_mode: '直租', ownership: '金租表外' })
  await post('/api/devices/batch-assign', { device_id: dev.id, batch_id: po.id })
  return dev.sn
}

test('S1-01 推进在途无采购验收：前端必须展示具体原因', async ({ page }) => {
  test.setTimeout(120_000)
  const sn = await apiSeed()
  try {
    await page.goto('http://localhost:8088/login', { waitUntil: 'networkidle' })
    await page.evaluate(() => localStorage.clear())
    await page.getByPlaceholder('请输入账号').fill('admin')
    await page.getByPlaceholder('请输入密码').fill('sie123')
    await page.getByRole('button', { name: /登.*录/ }).click()
    await page.waitForURL('http://localhost:8088/')
    await page.goto('http://localhost:8088/devices', { waitUntil: 'networkidle' })

    const row = page.locator('.device-list-table tbody tr').filter({ hasText: sn })
    await expect(row).toBeVisible({ timeout: 10000 })
    await row.getByRole('button', { name: '推进' }).click()
    const modal = page.locator('.n-modal')
    await modal.waitFor()

    // 节点=在途
    await selectOptionByText(modal, '节点', '在途', page)
    // 预筛：唯一合法目标状态「进行中」应自动选中（无需再开状态下拉）
    await expect(modal.locator('.n-form-item', { hasText: '状态' }).locator('.n-base-selection')).toContainText('进行中', { timeout: 5000 })

    // 提交后必须出现后端具体原因（409 detail：...尚未通过采购验收...）
    const before = await page.locator('.n-message', { hasText: '尚未通过采购验收' }).count()
    await modal.getByRole('button', { name: '确认推进' }).click()
    await expect.poll(
      async () => page.locator('.n-message', { hasText: '尚未通过采购验收' }).count(),
      { timeout: 15000 },
    ).toBeGreaterThan(before)
  } finally {
    if (ctx) await ctx.dispose()
  }
})
