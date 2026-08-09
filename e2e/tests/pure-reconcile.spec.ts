import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 债①回归 e2e：纯核销（不经 /pay）应反映到客户对账单「已回款」。
// 现状（修复前）：reconcile_invoice 只写 status=已核销/reconciled_at，不写 paid_date；而客户对账单
// received（report_service.py:156）、流水明细「回款/开票」标签（:205-207）、三流对账（invoice_service.py:77）
// 三处均读 paid_date → 绕过工作流直接核销时，发票已核销但对账单「已回款」漏计（少算回款、夸大未回款）。
// 修复（invoice_service.py reconcile_invoice 全核销分支）：matched >= 发票额 时，若 paid_date 尚空则补
// txn.transaction_date（is None 守卫→不覆盖工作流 pay→reconcile 已置的 paid_date，零回归）。
// 本 spec 走「建收款流水→直接核销」冷路径，全程不调 /invoices/{id}/pay，与 revenue-chain（走 /pay）互补。
// 共享 dev 库无隔离：RUN 派生唯一数据，前缀 E2E-/客户-E2E-/INV-/HT-F 供 globalTeardown（cleanup_e2e.py）清理
// （资金流水挂在本 E2E 项目下，随 project_id 级联清理）。

const API = '/api'
const RUN = Date.now().toString(36)

// money() 镜像 frontend/src/utils/format.ts：千分位 + 两位小数，无 ¥（UI 断言用它格式化真值）
function money(v: unknown): string {
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

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

// naive-ui n-select 下拉收敛（镜像 revenue-chain：过渡动画时序）
async function waitForMenu(page: Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}

test('纯核销（不经 /pay）→ 对账单已回款反映（债①回归）', async ({ page, request }) => {
  test.slow() // 共享 dev 库对账单查询偏慢 + UI 收口，给 3 倍预算
  const headers = await apiLogin(request)
  const custName = `客户-E2E-纯核销-${RUN}`

  // ---- 1~3. 项目 + 客户 + 销售合同（合同额 100000 不含税）----
  const proj = await apiPostJson(request, headers, '/projects', { name: `E2E-纯核销-${RUN}` }, '立项')
  const cust = await apiPostJson(request, headers, '/customers', { name: custName }, '客户')
  const contract = await apiPostJson(request, headers, '/contracts', {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 100000,
    contract_no: `HT-F-纯核销-${RUN}`,
  }, '销售合同')

  // ---- 4. 开票（含税 60000 → 不含税 I；捕获 I）----
  const invoice = await apiPostJson(request, headers, '/invoices', {
    contract_id: contract.id, amount: 60000,
    invoice_no: `INV-纯核销-${RUN}`, issue_date: '2026-09-20', due_date: '2026-10-20',
  }, '开票')
  const I = Number(invoice.amount_ex_tax)
  expect(I, '开票不含税额应 ≈ 53,097').toBeGreaterThan(50000)

  // ---- 5. 建一笔销售收款流水（IN，到账日 2026-09-25，金额覆盖发票）----
  //   这是「绕过工作流直接核销」的前提：先有钱进账的流水，才能把发票勾销到这笔流水。
  const txn = await apiPostJson(request, headers, '/capital/transactions', {
    project_id: proj.id, source_type: '租金收入', direction: 'IN',
    amount: 60000, transaction_date: '2026-09-25', contract_id: contract.id,
    idempotency_key: `纯核销-${RUN}`,
  }, '收款流水')

  // ---- 6. ★纯核销（不调 /invoices/{id}/pay）★——债①冷路径 ----
  const recRes = await request.post(`${API}/invoices/${invoice.id}/reconcile/${txn.id}`, { headers })
  expect(recRes.ok(), `核销失败: ${await recRes.text()}`).toBeTruthy()
  const recInv = await recRes.json()
  // ★核心断言：全额核销同步写 paid_date = 流水到账日（修复前此处为 null）
  expect(recInv.status, '核销后状态=已核销').toBe('已核销')
  expect(recInv.paid_date, 'paid_date 应=核销流水到账日 2026-09-25（修复前为 null）').toBe('2026-09-25')

  // ============ 追值法断言：对账单勾稽（received 不再漏计）============
  const st = await (await request.get(
    `${API}/reports/customer-statement?customer_id=${cust.id}`, { headers })).json()
  expect(Number(st.invoiced), '已开票 = 本链开票真值 I').toBe(I)
  // ★修复前这条断言会红：纯核销 received=0（paid_date 空）★
  expect(Number(st.received), '已回款 = I（★纯核销反映，修复前为 0★）').toBe(I)
  expect(Number(st.gap_uncollected), '未回款 = invoiced − received = 0').toBe(0)
  // 流水明细：该发票应显示为「回款」行（修复前 paid_date 空 → 显示「开票」）
  const recvLine = (st.line_items as Array<{ type: string; amount_ex_tax: string }>)
    .find((r) => r.type === '回款')
  expect(recvLine, '流水明细应含「回款」行（修复前只有「开票」）').toBeTruthy()
  expect(Number(recvLine!.amount_ex_tax), '回款行金额 = I').toBe(I)

  // ============ UI 收口（端到端验证铁律）：cfo 浏览器看对账单渲染回款 ============
  await uiLogin(page, 'cfo')
  await page.goto('/customer-statement')
  await expect(page.getByRole('heading', { name: '客户对账单' })).toBeVisible()

  // 选客户（共享库客户多，filterable 收窄后选「含本客户名」唯一项——naive-ui 下拉三坑防范）
  const picker = page.locator('.cs-picker')
  await picker.click()
  await waitForMenu(page, true)
  await picker.locator('input').fill(custName)
  await page.waitForTimeout(250) // 等 naive-ui 过滤收窄
  const myOption = page.locator('.n-base-select-option', { hasText: custName })
    .filter({ visible: true }).first()
  await expect(myOption).toBeVisible({ timeout: 5000 })
  await myOption.click()
  await waitForMenu(page, false)

  // 流水明细应渲染回款行金额 money(I)（与 revenue-chain 同款 DOM 等待：组件无 loading 标志，
  // 并行负载下查询可达数秒，直接对持久 DOM 做 toBeVisible 既是「加载完成」信号又是正确性断言）。
  // 修复前：该发票在流水明细里是「开票」行——金额仍是 money(I)，但语义是未回款；这里靠 API 层
  // 的 type=='回款' 断言辨别，UI 层断言金额可见即可（本客户仅此一张发票，money(I) 唯一）。
  const lineCard = page.locator('.n-card', { hasText: '流水明细' })
  await expect(lineCard.getByText(money(I)), '流水明细应渲染回款行金额').toBeVisible({ timeout: 30_000 })
})
