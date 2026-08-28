import { test, expect, type Page, type APIRequestContext } from '@playwright/test'

// 四期 W4 资金池分池 e2e（集成验证铁律）：
//   T1 API 全链：记银行借款→预付挂账→预付退回→预付核销→拆分付款(银行+自有)→还银行 + 余额不足拦截
//   T2 UI：付款管控「登记付款」弹窗按资金池拆分支付（金租/银行/自有各出多少）
// RUN 派生唯一数据 + E2E 前缀，globalTeardown 清理。
test.describe.configure({ mode: 'serial' })

const api = '/api'
const RUN = Date.now().toString(36)
let headers: Record<string, string>
let projId = ''

async function apiLogin(request: APIRequestContext) {
  const res = await request.post(`${api}/auth/login`, { form: { username: 'cfo', password: 'sie123' } })
  expect(res.ok()).toBeTruthy()
  const { access_token } = await res.json()
  return { Authorization: `Bearer ${access_token}` }
}

async function post(request: APIRequestContext, path: string, data: any, label: string, expectOk = true) {
  const r = await request.post(`${api}${path}`, { headers, data })
  if (expectOk) expect(r.ok(), `${label}: ${await r.text()}`).toBeTruthy()
  return r
}

async function pools(request: APIRequestContext) {
  const r = await request.get(`${api}/capital/pools`, { headers, params: { project_id: projId } })
  expect(r.ok()).toBeTruthy()
  const j = await r.json()
  return j.pools  // 端点返回 {project_id, pools: {POOL: balance}, labels}
}

async function uiLogin(page: Page) {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/, { timeout: 8000 })
}

test('T1 资金池 API 全链：借款/预付/退回/核销/拆分付款/还银行 + 余额拦截', async ({ request }) => {
  headers = await apiLogin(request)
  const proj = await (await post(request, '/projects', { name: `E2E-资金池-${RUN}` }, '立项')).json()
  projId = proj.id

  // S3（缺陷#9）：预付必带供应商与采购合同 → 先建主数据与合同
  const sup = await (await post(request, '/suppliers', { name: `E2E供应商-${RUN}`, type: '设备供应商' }, '供应商')).json()
  const cust = await (await post(request, '/customers', { name: `E2E客户-${RUN}`, industry: '互联网' }, '客户')).json()
  const sc = await (await post(request, '/contracts', {
    project_id: projId, type: 'SALES', biz_type: '算力租赁', party_id: cust.id,
    amount: 1_000_000, amount_incl_tax: 1_130_000, tax_rate: 0.13, lease_months: 12,
    contract_no: `E2EXS-${RUN}`,
  }, '销售合同')).json()
  const pc = await (await post(request, '/contracts', {
    project_id: projId, type: 'PURCHASE', biz_type: '算力租赁', party_id: sup.id,
    amount: 500_000, amount_incl_tax: 565_000, tax_rate: 0.13, parent_contract_id: sc.id,
    contract_no: `E2ECG-${RUN}`,
  }, '采购合同')).json()

  // 记银行借款 500 万 → 银行池 5M
  await post(request, '/capital/bank-loan',
    { project_id: projId, amount: 5_000_000, transaction_date: '2026-02-01' }, '记银行借款')
  // 自有池入金 200 万（通用记一笔，pool=OWN）
  await post(request, '/capital/transactions',
    { project_id: projId, source_type: '自有资金', direction: 'IN', amount: 2_000_000,
      transaction_date: '2026-02-01', pool: 'OWN' }, '自有入金')
  let p = await pools(request)
  expect(Number(p.BANK)).toBe(5_000_000)
  expect(Number(p.OWN)).toBe(2_000_000)

  // 预付 100 万（银行池出）→ 银行 4M / 预付挂账 1M
  await post(request, '/capital/prepayment',
    { project_id: projId, amount: 1_000_000, transaction_date: '2026-02-02', from_pool: 'BANK',
      supplier_id: sup.id, contract_id: pc.id }, '预付挂账')
  p = await pools(request)
  expect(Number(p.BANK)).toBe(4_000_000)
  expect(Number(p.PREPAY)).toBe(1_000_000)

  // 预付退回 40 万回银行池 → 挂账 0.6M / 银行 4.4M
  await post(request, '/capital/prepayment/refund',
    { project_id: projId, amount: 400_000, transaction_date: '2026-02-03', to_pool: 'BANK' }, '预付退回')
  // 预付核销 20 万（抵应付，不动现金）→ 挂账 0.4M
  await post(request, '/capital/prepayment/offset',
    { project_id: projId, amount: 200_000, transaction_date: '2026-02-04' }, '预付核销')
  p = await pools(request)
  expect(Number(p.PREPAY)).toBe(400_000)
  expect(Number(p.BANK)).toBe(4_400_000)

  // 拆分付款 150 万 = 银行 100 万 + 自有 50 万（申请→审批→登记 pool_splits）
  const pr = await (await post(request, '/payment-requests',
    { project_id: projId, amount: 1_500_000, reason: `E2E拆分付款-${RUN}` }, '付款申请')).json()
  const apprs = await (await request.get(`${api}/approvals`, { headers })).json()
  const myAppr = apprs.items.find((a: any) => a.biz_id === pr.id)
  await post(request, `/approvals/${myAppr.id}/approve`, {}, '审批通过')
  await post(request, `/payment-requests/${pr.id}/disburse`, {
    transaction_date: '2026-02-05',
    pool_splits: [{ pool: 'BANK', amount: 1_000_000 }, { pool: 'OWN', amount: 500_000 }],
  }, '拆分付款登记')
  p = await pools(request)
  expect(Number(p.BANK)).toBe(3_400_000)
  expect(Number(p.OWN)).toBe(1_500_000)

  // 余额不足拦截：拆分合计 ≠ 实付现金 → 400；银行池余额不足 → 400（INSUFFICIENT_POOL）
  const bad = await post(request, '/payment-requests',
    { project_id: projId, amount: 100_000, reason: `E2E坏拆分-${RUN}` }, '坏付款申请')
  const badPr = await bad.json()
  const apprs2 = await (await request.get(`${api}/approvals`, { headers })).json()
  const badAppr = apprs2.items.find((a: any) => a.biz_id === badPr.id)
  await post(request, `/approvals/${badAppr.id}/approve`, {}, '坏申请审批')
  const mismatch = await post(request, `/payment-requests/${badPr.id}/disburse`, {
    transaction_date: '2026-02-06',
    pool_splits: [{ pool: 'BANK', amount: 60_000 }],
  }, '拆分合计不符', false)
  expect(mismatch.status()).toBe(400)
  const insufficient = await post(request, '/capital/repay-bank',
    { project_id: projId, amount: 99_000_000, transaction_date: '2026-02-06' }, '余额不足', false)
  expect(insufficient.status()).toBe(400)
  expect((await insufficient.json()).detail.code).toBe('INSUFFICIENT_POOL')

  // 还银行 100 万 → 银行池 2.4M
  await post(request, '/capital/repay-bank',
    { project_id: projId, amount: 1_000_000, transaction_date: '2026-02-07' }, '还银行')
  p = await pools(request)
  expect(Number(p.BANK)).toBe(2_400_000)
  expect(Number(p.PREPAY)).toBe(400_000)
  expect(Number(p.OWN)).toBe(1_500_000)
})

test('T2 UI：登记付款弹窗按资金池拆分支付', async ({ page, request }) => {
  headers = await apiLogin(request)
  const proj = await (await post(request, '/projects', { name: `E2E-拆分UI-${RUN}` }, '立项')).json()
  projId = proj.id
  // 备资：银行池 200 万 + 自有池 300 万
  await post(request, '/capital/bank-loan',
    { project_id: projId, amount: 2_000_000, transaction_date: '2026-02-01' }, '记银行借款')
  await post(request, '/capital/transactions',
    { project_id: projId, source_type: '自有资金', direction: 'IN', amount: 3_000_000,
      transaction_date: '2026-02-01', pool: 'OWN' }, '自有入金')
  // 付款申请 100 万 → 审批通过
  const pr = await (await post(request, '/payment-requests',
    { project_id: projId, amount: 1_000_000, reason: `E2E-UI拆分-${RUN}` }, '付款申请')).json()
  const apprs = await (await request.get(`${api}/approvals`, { headers })).json()
  const myAppr = apprs.items.find((a: any) => a.biz_id === pr.id)
  await post(request, `/approvals/${myAppr.id}/approve`, {}, '审批通过')

  await uiLogin(page)
  await page.goto('/payments')
  // 已批准申请 → 登记付款
  await page.getByRole('button', { name: '登记付款' }).first().click()
  const modal = page.locator('.n-modal', { hasText: '登记付款' })
  await expect(modal).toBeVisible()
  // 填日期
  await modal.locator('.n-date-picker input').first().fill('2026-02-10')
  await modal.locator('.n-date-picker input').first().press('Enter')
  // 勾选拆分支付 → 银行 60 万 + 自有 40 万
  await modal.getByText('按资金池拆分').click()
  await modal.locator('.n-form-item', { hasText: '银行池出' }).locator('input').fill('600000')
  await modal.locator('.n-form-item', { hasText: '自有池出' }).locator('input').fill('400000')
  await modal.getByRole('button', { name: '登记' }).click()
  await expect(modal).toBeHidden({ timeout: 15000 })

  // API 追值：银行池 140 万 / 自有池 260 万
  const p = await pools(request)
  expect(Number(p.BANK)).toBe(1_400_000)
  expect(Number(p.OWN)).toBe(2_600_000)
})