import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 一期终审 Step 2 · 营收全链路串烧（端到端铁律 + 跨模块集成回归网）。
// 现有 22 个 e2e 里每个营收模块都只孤立测，没有任何 spec 把「立项→销售合同→采购→设备点亮→
// 计费→开票→回款→对账单」串成一条 journey；尤其回款（/pay）从未被任何 e2e 触发，对账单只验过
// 全零场景（w9 F3）。本 spec 一条绿 = 整条赚钱链路没断（A 模块写入的数据正确流到 Z 模块）。
// 金租/回租/折旧已被 w5_6/w7_8 覆盖，不串进来（避免重复 + 巨脆）。
// 共享 dev 库无测试隔离：RUN 派生唯一数据，前缀 E2E- 供 globalTeardown（cleanup_e2e.py）清理。

const API = '/api'
const RUN = Date.now().toString(36)

// money() 镜像 frontend/src/utils/format.ts：千分位 + 两位小数，无 ¥（UI 断言用它格式化本链真值）
function money(v: unknown): string {
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

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

// POST 造数 + 断言 ok + 回 json（失败把 body 吐进断言信息，定位用）
async function apiPostJson(
  request: APIRequestContext, headers: Record<string, string>,
  path: string, data: Record<string, unknown>, label: string,
) {
  const r = await request.post(`${API}${path}`, { headers, data })
  expect(r.ok(), `${label} 失败: ${await r.text()}`).toBeTruthy()
  return r.json()
}

// naive-ui n-select 下拉收敛（镜像 w7_8：过渡动画时序）
async function waitForMenu(page: Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}

// API 推进单台设备到点亮验收（7 节点 × 进行中+已完成；点亮传 actual_date 激活运营/起折旧）
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

test('营收全链路串烧：立项→销售合同→采购→设备点亮→按台计费→开票→回款→对账单勾稽', async ({ page, request }) => {
  test.slow() // 14 轮设备推进 + 共享 dev 库对账单查询偏慢，给 3 倍预算
  const headers = await apiLogin(request)
  // 前缀对齐 cleanup_e2e.py：客户须匹配 ^客户-E2E、型号须匹配 ^E2E-（两者无 project_id，不走级联）。
  // 其余实体（项目 E2E-/订单/设备/计费/合同）靠 project_id 级联或 INV-/GPU- 独立判据清理。
  const custName = `客户-E2E-串烧-${RUN}`

  // ---- 1~6. 造主体 + 销售合同 + 型号 + 采购订单 + 设备（逐跳 id 串接）----
  const proj = await apiPostJson(request, headers, '/projects', { name: `E2E-串烧-${RUN}` }, '立项')
  const cust = await apiPostJson(request, headers, '/customers', { name: custName }, '客户')
  const contract = await apiPostJson(request, headers, '/contracts', {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 1_000_000,
    contract_no: `HT-串烧-${RUN}`,
  }, '销售合同')
  const model = await apiPostJson(request, headers, '/equipment-models', {
    name: `E2E-型号-串烧-${RUN}`, category: '大卡', gpu_count: 8,
  }, '设备型号')
  // 采购订单（单设备，链覆盖；其 delivery_stages 不影响按台计费——计费走 device_stages.点亮验收）
  const order = await apiPostJson(request, headers, '/orders', {
    project_id: proj.id, equipment_model_id: model.id, quantity: 1, unit_price: 960000,
  }, '采购订单')
  // monthly_price 供按台计费；purchase_value 供上架建资产卡 + 点亮激活（表内自有）
  const device = await apiPostJson(request, headers, '/devices', {
    project_id: proj.id, equipment_model_id: model.id, order_id: order.id,
    sales_contract_id: contract.id, monthly_price: 100000, purchase_value: 960000,
    ownership: '表内自有', leasing_mode: '自有',
  }, '设备')

  // ---- 7. 推进到点亮验收（点亮日=2026-09-01 月初 → 整月计费，算术干净）----
  await advanceToLit(request, headers, device.id, '2026-09-01')

  // ---- 8. 按台计费 period 1（整月）→ 捕获 amount_ex_tax=B（追值法：读真值，不手算）----
  const billing = await apiPostJson(request, headers, '/billings/device', {
    device_id: device.id, contract_id: contract.id, period_index: 1,
    billing_date: '2026-09-30', idempotency_key: `${device.id}-1`,
  }, '按台计费')
  const B = Number(billing.amount_ex_tax)
  // 点读校验：amount_ex_tax 应是不含税额（~88k），非含税 100k，也非空（防字段意外缺失）
  expect(B, '计费 amount_ex_tax 应 ≈ 88,495（不含税）').toBeGreaterThan(80000)
  expect(B).toBeLessThan(99000)

  // ---- 9a. 开票（含税 60,000 → ex-tax ≈ 53,097；故意 ≠ B，辨析 billed↔invoiced 混淆回归）----
  const invoice = await apiPostJson(request, headers, '/invoices', {
    contract_id: contract.id, amount: 60000,
    invoice_no: `INV-串烧-${RUN}`, issue_date: '2026-09-20', due_date: '2026-10-20',
  }, '开票')
  const I = Number(invoice.amount_ex_tax)
  expect(I, '开票 amount_ex_tax 应 ≈ 53,097（不含税）').toBeGreaterThan(50000)
  expect(I).toBeLessThan(55000)

  // ---- 9b. 回款：/pay 置 paid_date → 对账单 received 读的就是 paid_date IS NOT NULL
  //         （⚠️ reconcile 核销只写 matched_amount 不写 paid_date → 纯核销不反映到对账单 received，
  //          像个潜在隐性 bug，但不在本 spec 修；这里用 /pay 这条干净路径）
  const payRes = await request.post(`${API}/invoices/${invoice.id}/pay`,
    { headers, data: { paid_date: '2026-09-25' } })
  expect(payRes.ok(), `回款 /pay 失败: ${await payRes.text()}`).toBeTruthy()

  // ============ 追值法断言：对账单四 KPI（billed/invoiced/received 全 ex-tax 口径自洽）============
  const st = await (await request.get(
    `${API}/reports/customer-statement?customer_id=${cust.id}`, { headers })).json()
  expect(Number(st.contract_amount), '合同额原值（不含税 c.amount，与 billed 同口径）').toBe(1_000_000)
  expect(Number(st.billed), '已计费 = 本链计费真值 B').toBe(B)
  expect(Number(st.invoiced), '已开票 = 本链开票真值 I').toBe(I)
  expect(Number(st.received), '已回款 = /pay 后 = invoiced').toBe(I)
  expect(Number(st.gap_uncollected), '未回款 = invoiced − received，ex-tax 自洽').toBe(0)
  // gap_unbilled 均不含税同口径（c.amount 不含税 − billed 不含税）；非 0 仅因本链只计费 1 期、合同额远大于单期计费
  expect(Number(st.gap_unbilled), '未计费 = contract_amount − billed（同不含税口径）')
    .toBeCloseTo(1_000_000 - B, 2)

  // 设备模块钩进链：点亮验收 + 有计费 + 表内自有 → inventory-summary 该型号在租 ≥ 1
  const inv = await (await request.get(`${API}/devices/inventory-summary`, { headers })).json()
  const mine = inv.items.find((m: { model_id: string; model_name: string }) =>
    m.model_id === model.id || m.model_name === model.name)
  expect(mine, '该型号应出现在库存看板').toBeTruthy()
  expect(Number(mine.rented), '点亮+计费后该设备计入「在租」').toBeGreaterThanOrEqual(1)

  // ============ UI 收口（端到端验证铁律）：cfo 浏览器看对账单渲染本链数据 ============
  await uiLogin(page, 'cfo')
  await page.goto('/customer-statement')
  await expect(page.getByRole('heading', { name: '客户对账单' })).toBeVisible()

  // 选客户（共享库客户多，filterable 收窄后选「含本客户名」的唯一项——naive-ui 下拉三坑防范）
  const picker = page.locator('.cs-picker')
  await picker.click()
  await waitForMenu(page, true)
  await picker.locator('input').fill(custName)
  await page.waitForTimeout(250) // 等 naive-ui 过滤收窄
  // 用 hasText 钉死「我的客户」选项，比「第一个可见项」更稳（防并行负载下过滤未收窄时误选）
  const myOption = page.locator('.n-base-select-option', { hasText: custName })
    .filter({ visible: true }).first()
  await expect(myOption).toBeVisible({ timeout: 5000 })
  await myOption.click()
  await waitForMenu(page, false)

  // ⚠️ 组件无 loading 标志、loadStatement 慢时 stmt 仍显示上一客户旧值（并行负载下查询可达数秒）。
  //   选完我的客户后，直接对「流水明细里我的计费真值 money(B)」做 toBeVisible（30s 预算）：它会在
  //   stmt 切到本客户数据后出现，既是「加载完成」信号又是正确性断言。money(B) 唯一（本链计费额），
  //   不会误中上一客户旧值。曾试 waitForResponse 钉 URL，但谓词偶发不匹配（响应到了却未命中）→ 弃用，
  //   直接断言可见 DOM 更稳，也更贴合「端到端铁律」（验用户真看到的渲染）。
  //   注意：发票 /pay 后 paid_date 非空 → 流水明细里该发票显示为「回款」（非「开票」）。
  const lineCard = page.locator('.n-card', { hasText: '流水明细' })
  await expect(lineCard.getByText(money(B)), '流水明细应含计费行金额').toBeVisible({ timeout: 30_000 })
  await expect(lineCard.getByText(money(I)), '流水明细应含回款行金额').toBeVisible({ timeout: 10_000 })
})
