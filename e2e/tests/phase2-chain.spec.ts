import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 二期 W13-14 全链联调串烧（二期收官，端到端铁律）：
//   立项(经营租赁/自有) → 主数据 → 销售合同(R1 自动判定经营租赁+EBS 出站) → 采购 → 批次+2 台设备
//   → 在途自动运输险(分摊 golden 600/400) → 7 节点点亮(财产险+资产激活) → 按台计费(golden 含税 10 万)
//   → 预付款月结转 1000 → 开票(USD 7.10) → 进项认证/抵扣 → 收款核销(USD 7.20)
//   → 汇兑损益 IN 1000 按设备 60万/40万 分摊 600/400 → 客户对账单三流追值 → UI 收口(/ebs 日志可见)
// 全部追值法（读真值断言，不手算裸值）；RUN 派生 + E2E-/HT-F/INV- 前缀，cleanup_e2e 清理。

const API = '/api'
const RUN = Date.now().toString(36)
const STAGES = ['订货', '在途', '到货', '己方压测', '上架', '客户压测', '点亮验收']

async function apiLogin(request: APIRequestContext, username = 'cfo', password = 'sie123') {
  const res = await request.post(`${API}/auth/login`, { form: { username, password } })
  expect(res.ok(), `API 登录失败: ${username}`).toBeTruthy()
  const { access_token } = await res.json()
  return { Authorization: `Bearer ${access_token}` }
}
async function post(request: APIRequestContext, headers: any, path: string, data: any, label: string) {
  const r = await request.post(`${API}${path}`, { headers, data })
  expect(r.ok(), `${label}: ${await r.text()}`).toBeTruthy()
  return r.json()
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

test('二期全链串烧：立项→合同判定→采购→保险→点亮计费→预付款→开票进项→收款核销汇兑→对账', async ({ page, request }) => {
  test.slow() // 2 台设备 ×7 节点推进 + 共享库，给 3 倍预算
  const headers = await apiLogin(request)

  // ---- 1. 立项（经营租赁/自有，R1 输入）+ 主数据 + 投保配置 ----
  const proj = await post(request, headers, '/projects',
    { name: `E2E-链-${RUN}`, business_type: '经营租赁', leasing_mode: '自有' }, '立项')
  const cust = await post(request, headers, '/customers', { name: `客户-E2E-链-${RUN}` }, '客户')
  const sup = await post(request, headers, '/suppliers',
    { name: `E2E供应商-链-${RUN}`, type: '设备供应商' }, '供应商')
  const model = await post(request, headers, '/equipment-models',
    { name: `E2E-型号-链-${RUN}`, category: '大卡', gpu_count: 8 }, '型号')
  await post(request, headers, '/insurance/configs',
    { policy_type: '运输险', default_rate: 0.001, insured_ratio: 1, cost_allocation: '资产原值' }, '运输险配置')
  await post(request, headers, '/insurance/configs',
    { policy_type: '财产险', default_rate: 0.002, insured_ratio: 1, cost_allocation: '长期待摊' }, '财产险配置')

  // ---- 2. 销售合同（USD）：R1 自动判定经营租赁 + EBS 判定快照出站 ----
  const sales = await post(request, headers, '/contracts', {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 1000000,
    contract_no: `HT-F${RUN}`, monthly_rent: 113000,
    start_date: '2026-09-01', end_date: '2027-08-31', currency_code: 'USD',
  }, '销售合同')
  expect(sales.revenue_method, 'R1：经营租赁/自有/SALES → 经营租赁（D1 真实枚举）').toBe('经营租赁')
  const judgeLogs = await (await request.get(`${API}/ebs/logs`, {
    headers, params: { entity_type: 'contract_revenue_method', limit: 50 },
  })).json()
  const myJudge = judgeLogs.items.filter((l: any) => l.entity_id === sales.id)
  expect(myJudge.length, '判定结果应出站 EBS Mock').toBeGreaterThanOrEqual(1)
  expect(myJudge[0].request_payload.revenue_method).toBe('经营租赁')

  // ---- 3. 采购：采购合同 + 批次订单 + 2 台设备（60万/40万；device1 预付款 12000）----
  const purchase = await post(request, headers, '/contracts', {
    project_id: proj.id, type: 'PURCHASE', party_id: sup.id, amount: 2000000,
  }, '采购合同')
  const batch = await post(request, headers, '/orders', {
    project_id: proj.id, equipment_model_id: model.id, quantity: 2, unit_price: 600000, is_batch: true,
  }, '批次订单')
  const devSpecs = [
    { purchase_value: 600000, monthly_price: 100000, prepayment_amount: 12000 },
    { purchase_value: 400000, monthly_price: 80000, prepayment_amount: 0 },
  ]
  const devices: any[] = []
  for (const spec of devSpecs) {
    const d = await post(request, headers, '/devices', {
      project_id: proj.id, equipment_model_id: model.id, sales_contract_id: sales.id,
      ownership: '表内自有', ...spec,
    }, '设备')
    await post(request, headers, '/devices/batch-assign', { device_id: d.id, batch_id: batch.id }, '挂批次')
    devices.push(d)
  }

  // ---- 4. 设备推进 7 节点：在途自动运输险 → 点亮财产险 + 资产激活 ----
  for (const d of devices) {
    for (const stage of STAGES) {
      for (const status of ['进行中', '已完成']) {
        const body: any = { stage, status }
        if (stage === '点亮验收' && status === '已完成') body.actual_date = '2026-09-01'
        await post(request, headers, `/devices/${d.id}/stage`, body, `推进${d.sn}${stage}${status}`)
      }
    }
  }
  // 保险追值：运输险 1 张（批次，保额 100 万×1，保费 1000，分摊 600/400）；财产险 2 张（每台一张）
  const pols = await (await request.get(`${API}/insurance/policies`, {
    headers, params: { project_id: proj.id },
  })).json()
  const transport = pols.items.find((p: any) => p.policy_type === '运输险')
  expect(transport, '在途应自动建运输险').toBeTruthy()
  expect(Number(transport.insured_amount)).toBe(1000000)
  expect(Number(transport.premium_amount)).toBe(1000)
  const tpDetail = await (await request.get(`${API}/insurance/policies/${transport.id}`, { headers })).json()
  const tpByDev = Object.fromEntries(tpDetail.devices.map((r: any) => [r.device_id, Number(r.allocated_amount)]))
  expect(tpByDev[devices[0].id], '运输险分摊 golden：60万设备分 600').toBe(600)
  expect(tpByDev[devices[1].id], '运输险分摊 golden：40万设备分 400').toBe(400)
  const property = pols.items.filter((p: any) => p.policy_type === '财产险')
  expect(property.length, '点亮应每台自动建财产险').toBe(2)

  // ---- 5. 点亮按台计费（golden：9/1 点亮整月，含税 100,000 / 不含税 88,495.58）+ 预付款月结转 1000 ----
  const billing = await post(request, headers, '/billings/device', {
    device_id: devices[0].id, contract_id: sales.id, period_index: 1,
    billing_date: '2026-09-30', idempotency_key: `${devices[0].id}-1`,
  }, '按台计费')
  const B = Number(billing.amount_ex_tax)
  expect(Number(billing.amount), '整月含税 10 万').toBe(100000)
  expect(B).toBeGreaterThan(88000)
  expect(B).toBeLessThan(89000)
  const dev1AfterBill = (await (await request.get(`${API}/devices`, {
    headers, params: { project_id: proj.id },
  })).json()).items.find((d: any) => d.id === devices[0].id)
  expect(Number(dev1AfterBill.prepayment_settled_amount), '预付款月结转 12000/12=1000').toBe(1000)
  expect(dev1AfterBill.prepayment_settled).toBe(false)

  // ---- 6. 开票（USD 10,000 @7.10）+ 进项认证/抵扣 ----
  const invoice = await post(request, headers, '/invoices', {
    contract_id: sales.id, amount: 10000, invoice_no: `INV-E2E-链-${RUN}`,
    issue_date: '2026-09-20', currency_code: 'USD', invoice_rate: 7.10,
  }, '开票')
  const I = Number(invoice.amount_ex_tax) // 8849.56
  const pinv = await post(request, headers, '/invoices', {
    contract_id: purchase.id, amount: 1130, invoice_no: `INV-E2E-进-${RUN}`, issue_date: '2026-09-05',
  }, '采购发票')
  await post(request, headers, `/invoices/${pinv.id}/certify`, { paid_date: '2026-09-10' }, '进项认证')
  const deducted = await post(request, headers, `/invoices/${pinv.id}/deduct`, {}, '进项抵扣')
  expect(deducted.certification_status, '进项应抵扣').toBe('已抵扣')
  const ledger = await (await request.get(`${API}/invoices/input-tax-ledger`, {
    headers, params: { project_id: proj.id },
  })).json()
  const dedRow = ledger.items.find((r: any) => r.certification_status === '已抵扣')
  expect(Number(dedRow.tax_amount), '进项台账：1130 含税 13% → 税 130').toBe(130)

  // ---- 7. 收款核销（USD 10,000 @7.20 收得多=收益）→ 汇兑 IN 1000 按设备分摊 600/400 ----
  const txn = await post(request, headers, '/capital/transactions', {
    project_id: proj.id, source_type: '租金收入', direction: 'IN', amount: 10000,
    transaction_date: '2026-09-25', currency_code: 'USD', settlement_rate: 7.20,
  }, '收款流水')
  await post(request, headers, '/payment-settlements', {
    txn_id: txn.id, allocations: [{ invoice_id: invoice.id, amount: 10000 }],
  }, '收款核销')
  const invAfter = (await (await request.get(`${API}/invoices/pool`, { headers })).json())
    .items.find((i: any) => i.id === invoice.id)
  expect(invAfter.status, '核销满 → 已核销').toBe('已核销')
  const fxSetts = await (await request.get(`${API}/payment-settlements`, {
    headers, params: { invoice_id: invoice.id },
  })).json()
  const fxRows = fxSetts.items.filter((s: any) => s.device_id)
  expect(fxRows.length, '汇兑应按设备逐台拆 2 行').toBe(2)
  const fxByDev = Object.fromEntries(fxRows.map((r: any) => [r.device_id, Number(r.amount)]))
  expect(fxByDev[devices[0].id], '汇兑分摊 golden：60万设备分 600').toBe(600)
  expect(fxByDev[devices[1].id], '汇兑分摊 golden：40万设备分 400').toBe(400)

  // ---- 8. 三流对账（追值法：billed=B / invoiced=I / received=I） ----
  const st = await (await request.get(`${API}/reports/customer-statement`, {
    headers, params: { customer_id: cust.id },
  })).json()
  expect(Number(st.billed), '已计费 = 本链计费真值 B').toBeCloseTo(B, 2)
  expect(Number(st.invoiced), '已开票 = 本链开票真值 I').toBeCloseTo(I, 2)
  expect(Number(st.received), '已回款 = 核销后 = invoiced').toBeCloseTo(I, 2)

  // ---- 9. UI 收口：/ebs 日志页可见判定快照出站 ----
  await uiLogin(page)
  await page.goto('/ebs')
  await expect(page.getByRole('heading', { name: 'EBS 同步监控' })).toBeVisible()
  await expect(page.locator('.n-card', { hasText: '同步日志' })).toContainText('contract_revenue_method', { timeout: 10_000 })
  await expect(page.locator('.n-card', { hasText: '同步日志' })).toContainText('MOCK_SUCCESS')
})
