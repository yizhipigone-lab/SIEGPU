import { test, expect, type Page, type APIRequestContext } from '@playwright/test'

// 项目血缘树 e2e（集成验证铁律）：
//   API 造全链数据：项目 → 销售合同(→销售订单；参照采购合同→批次订单→2台设备含预付款) + 金租申请
//   断言一：GET /projects/{id}/relationships 树结构（嵌套/预付款状态/金租归属）
//   断言二：项目工作台「业务对象关联」卡片树 UI（合同嵌套/预付款标签/单台穿透）
const api = '/api'
const RUN = Date.now().toString(36)

async function apiLogin(request: APIRequestContext, username = 'cfo') {
  const res = await request.post(`${api}/auth/login`, { form: { username, password: 'sie123' } })
  expect(res.ok(), `API 登录失败: ${username}`).toBeTruthy()
  const { access_token } = await res.json()
  return { Authorization: `Bearer ${access_token}` }
}

async function post(request: APIRequestContext, headers: any, path: string, data: any, label: string) {
  const r = await request.post(`${api}${path}`, { headers, data })
  expect(r.ok(), `${label}: ${await r.text()}`).toBeTruthy()
  return r.json()
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

test('项目血缘树：API 结构 + 工作台卡片树（批次汇总 + 单台穿透）', async ({ page, request }) => {
  const headers = await apiLogin(request)

  // ---- 主数据 ----
  const sup = await post(request, headers, '/suppliers',
    { name: `E2E供应商-树-${RUN}`, type: '设备供应商' }, '供应商')
  const fund = await post(request, headers, '/suppliers',
    { name: `E2E金租-树-${RUN}`, type: '资金供应商' }, '金租机构')
  const cust = await post(request, headers, '/customers', { name: `E2E客户-树-${RUN}` }, '客户')
  const model = await post(request, headers, '/equipment-models',
    { name: `E2E-型号-树-${RUN}`, category: '大卡', gpu_count: 8 }, '型号')

  // ---- 全链数据 ----
  const proj = await post(request, headers, '/projects', { name: `E2E-血缘-${RUN}` }, '立项')
  const salesNo = `HT-S-${RUN}`
  const sales = await post(request, headers, '/contracts', {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 1000000,
    contract_no: salesNo, monthly_rent: 113000,
  }, '销售合同')
  const purchaseNo = `HT-P-${RUN}`
  const purchase = await post(request, headers, '/contracts', {
    project_id: proj.id, type: 'PURCHASE', party_id: sup.id, amount: 900000,
    contract_no: purchaseNo, parent_contract_id: sales.id,
  }, '采购合同（参照销售）')
  const batchName = `E2E批次-${RUN}`
  const batch = await post(request, headers, '/orders', {
    project_id: proj.id, contract_id: purchase.id, equipment_model_id: model.id,
    quantity: 2, unit_price: 450000, is_batch: true, batch_name: batchName,
  }, '采购批次订单')
  await post(request, headers, '/sales-orders', {
    project_id: proj.id, contract_id: sales.id, equipment_model_id: model.id,
    quantity: 2, monthly_rent_per_unit: 56500, total_monthly_rent: 113000,
  }, '销售订单')
  const devSns: string[] = []
  for (const prepay of [12000, 0]) {
    const d = await post(request, headers, '/devices', {
      project_id: proj.id, equipment_model_id: model.id, sales_contract_id: sales.id,
      ownership: '表内自有', purchase_value: 450000, monthly_price: 56500,
      prepayment_amount: prepay,
    }, '设备')
    await post(request, headers, '/devices/batch-assign',
      { device_id: d.id, batch_id: batch.id }, '挂批次')
    devSns.push(d.sn)
  }
  const lp = await post(request, headers, '/leasing/processes', {
    project_id: proj.id, supplier_id: fund.id, total_amount: 800000,
    annual_rate: 0.04, term_periods: 12, payment_freq: '月', repayment_method: '等额本息',
  }, '金租申请')

  // ---- 断言一：relationships API 树结构 ----
  const treeRes = await request.get(`${api}/projects/${proj.id}/relationships`, { headers })
  expect(treeRes.ok(), `relationships: ${await treeRes.text()}`).toBeTruthy()
  const tree = await treeRes.json()
  expect(tree.project.id).toBe(proj.id)
  expect(tree.sales_contracts.length).toBe(1)
  const sc = tree.sales_contracts[0]
  expect(sc.contract_no).toBe(salesNo)
  expect(sc.sales_orders.length).toBe(1)
  expect(sc.purchase_contracts.length).toBe(1)
  const pc = sc.purchase_contracts[0]
  expect(pc.contract_no).toBe(purchaseNo)
  expect(pc.orders.length).toBe(1)
  const order = pc.orders[0]
  expect(order.devices.length).toBe(2)                       // 单台穿透数据层
  expect(order.prepayment.status).toBe('已付挂账')            // 12000 未结转
  expect(order.prepayment.total).toBe(12000)
  // 金租申请挂在项目下（ leasing_processes.project_id ）
  expect(tree.leasing_processes.length).toBe(1)
  expect(tree.leasing_processes[0].id).toBe(lp.id)

  // ---- 断言二：工作台卡片树 UI ----
  await uiLogin(page)
  await page.goto(`/projects/${proj.id}/workspace`)
  await expect(page.getByText('业务对象关联')).toBeVisible({ timeout: 10000 })

  // 金租申请卡片（带计数，避开工作流步骤同名步骤）
  const lpCard = page.locator('.n-card', { hasText: '金租申请（1）' })
  await expect(lpCard).toBeVisible()
  await expect(lpCard.getByText(`E2E金租-树-${RUN}`)).toBeVisible()

  // 销售合同 → 销售订单 / 采购合同 嵌套
  const scCard = page.locator('.n-card', { hasText: salesNo })
  await expect(scCard).toBeVisible()
  await expect(scCard.getByText('销售订单（1）')).toBeVisible()
  await expect(scCard.getByText(purchaseNo)).toBeVisible()
  await expect(scCard.getByText(batchName)).toBeVisible()

  // 预付款状态：已付挂账（批次汇总层）
  await expect(scCard.getByText('预付款 已付挂账')).toBeVisible()

  // 单台穿透：展开前 SN 不可见 → 点 chevron 展开 → SN 可见
  const sn = devSns[0]
  await expect(scCard.getByText(sn)).toBeHidden()
  await page.getByTestId(`toggle-devices-${order.id}`).click()
  await expect(scCard.getByText(sn)).toBeVisible()
  await expect(scCard.getByText(devSns[1])).toBeVisible()
})

test('P1：工作台直接发起金租申请（预填项目）→ 卡片树实时出现', async ({ page, request }) => {
  const headers = await apiLogin(request)
  const RUN2 = `${RUN}lz`
  const fund = await post(request, headers, '/suppliers',
    { name: `E2E金租-发起-${RUN2}`, type: '资金供应商' }, '金租机构')
  const proj = await post(request, headers, '/projects', { name: `E2E-发起-${RUN2}` }, '立项')

  await uiLogin(page)
  await page.goto(`/projects/${proj.id}/workspace`)
  await expect(page.getByText('业务对象关联')).toBeVisible({ timeout: 10000 })
  const lpCard = page.locator('.n-card', { hasText: '金租申请（0）' })
  await expect(lpCard).toBeVisible()

  await page.getByRole('button', { name: '发起金租申请' }).click()
  const modal = page.locator('.n-modal', { hasText: '发起金租申请' })
  await modal.waitFor()
  // naive-ui 下拉（虚拟滚动只渲染可见窗口）：展开 → 键入名称收窄 → 点唯一选项
  const leaseSel = modal.getByTestId('lease-supplier').locator('.n-base-selection')
  await leaseSel.click()
  await leaseSel.locator('input').fill(`E2E金租-发起-${RUN2}`)
  await page.waitForTimeout(400)
  const opt = page.locator('.n-base-select-option', { hasText: `E2E金租-发起-${RUN2}` })
    .filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible', timeout: 15000 })
  await opt.click()
  await modal.getByTestId('lease-amount').locator('input').fill('800000')
  await modal.getByTestId('lease-submit').click()
  await expect(modal).toBeHidden({ timeout: 15000 })

  // 卡片树刷新：计数翻 1 + 机构名可见
  await expect(page.locator('.n-card', { hasText: '金租申请（1）' })).toBeVisible({ timeout: 8000 })
  await expect(page.locator('.n-card', { hasText: '金租申请' }).getByText(`E2E金租-发起-${RUN2}`)).toBeVisible()

  // API 追值：申请确实挂在项目下
  const procs = await (await request.get(`${api}/leasing/processes`, {
    headers, params: { project_id: proj.id },
  })).json()
  expect(procs.items.length).toBe(1)
  expect(Number(procs.items[0].total_amount)).toBe(800000)
  expect(procs.items[0].supplier_id).toBe(fund.id)
})
test('P1：项目总览增强——KPI 行 + 财务列 + 搜索/状态筛选', async ({ page, request }) => {
  const headers = await apiLogin(request)
  const RUN3 = `${RUN}pf`
  // 造两个项目：A 带财务数据（销售合同 1000 + 金租放款 600 + 预付 500），B 空项目（筛选用对照）
  const projA = await post(request, headers, '/projects', { name: `E2E-总览A-${RUN3}` }, '立项A')
  const projB = await post(request, headers, '/projects', { name: `E2E-总览B-${RUN3}` }, '立项B')
  const cust = await post(request, headers, '/customers', { name: `E2E客户-总览-${RUN3}` }, '客户')
  const fund = await post(request, headers, '/suppliers',
    { name: `E2E金租-总览-${RUN3}`, type: '资金供应商' }, '金租机构')
  const model = await post(request, headers, '/equipment-models',
    { name: `E2E-型号-总览-${RUN3}`, category: '大卡' }, '型号')
  await post(request, headers, '/contracts', {
    project_id: projA.id, type: 'SALES', party_id: cust.id, amount: 900, amount_incl_tax: 1000,
  }, '销售合同')
  const lpRes = await post(request, headers, '/leasing/processes', {
    project_id: projA.id, supplier_id: fund.id, total_amount: 800,
    annual_rate: 0.048, term_periods: 12, payment_freq: '月', repayment_method: '等额本息',
  }, '金租申请')
  // 期3 #5：验收通过才能放款 → 先造采购订单 + 采购验收通过
  const order = await post(request, headers, '/orders', {
    project_id: projA.id, equipment_model_id: model.id, quantity: 1, unit_price: 450000,
  }, '采购订单')
  const acc = await post(request, headers, '/acceptances', {
    project_id: projA.id, acceptance_type: '采购验收', order_id: order.id,
  }, '采购验收')
  await post(request, headers, `/acceptances/${acc.id}/approve`, {}, '采购验收通过')
  // 放款 600（disbursements 端点，actual_disbursement_amount 聚合来源）
  await post(request, headers, `/leasing/processes/${lpRes.id}/disbursements`, {
    amount: 600, disbursement_date: '2026-02-01', acceptance_id: acc.id,
  }, '金租放款')
  const dev = await post(request, headers, '/devices', {
    project_id: projA.id, equipment_model_id: model.id, prepayment_amount: 500,
    purchase_value: 450000, monthly_price: 50000, ownership: '表内自有',
  }, '设备（预付 500）')
  expect(dev.id).toBeTruthy()

  await uiLogin(page)
  await page.goto('/portfolio')
  // KPI 行渲染
  await expect(page.getByText('项目总数')).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('销售合同总额')).toBeVisible()
  // 项目 A 行：财务三列真值
  const rowA = page.locator(`tr[data-project="E2E-总览A-${RUN3}"]`)
  await expect(rowA).toBeVisible()
  await expect(rowA).toContainText('1,000.00')   // 销售合同额（含税优先）
  await expect(rowA).toContainText('600.00')     // 金租已放款
  await expect(rowA).toContainText('500.00')     // 预付余额
  // 搜索收窄：搜 A 见 A 不见 B
  await page.getByTestId('pf-search').locator('input').fill(`总览A-${RUN3}`)
  await expect(rowA).toBeVisible()
  await expect(page.locator(`tr[data-project="E2E-总览B-${RUN3}"]`)).toBeHidden()
  // 状态筛选：两个项目都是「进行中」→ 选中后两行都在
  await page.getByTestId('pf-search').locator('input').clear()
  await page.getByTestId('pf-status').locator('.n-base-selection').click()
  const opt = page.locator('.n-base-select-option', { hasText: '进行中' }).filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await expect(rowA).toBeVisible()
  await expect(page.locator(`tr[data-project="E2E-总览B-${RUN3}"]`)).toBeVisible()
})
