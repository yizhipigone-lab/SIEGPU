import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 三期 §4.3 对账中心 —— 端到端（端到端铁律）：
//   API 备数（销售合同 + 点亮计费 → 已计未开差异；确认收入审批通过 → 已确认未开）
//   → UI 七维卡渲染 → 维度 1 行标红且 flags 文案正确 → 维度 6 注入 3 条模拟差异（验收管道）
//   → 维度 7 差异明细含本合同 → API 追值（注入后恰好 3 条业财差异）。
// 共享 dev 库无隔离：合同号 HT-F{RUN} 唯一锚点；cleanup_e2e 清理。

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

test('对账中心：7 维渲染 + 差异标红 + 业财注入管道 + 差异明细追值', async ({ page, request }) => {
  const headers = await apiLogin(request)
  const contractNo = `HT-F${RUN}`

  // ---- 备数：项目 + 销售合同 + 点亮设备 + 计费（已计未开）+ 确认收入审批通过（已确认未开）----
  const proj = await post(request, headers, '/projects', { name: `E2E-对账-${RUN}` }, '立项')
  const cust = await post(request, headers, '/customers', { name: `客户-E2E-对账-${RUN}` }, '客户')
  const contract = await post(request, headers, '/contracts', {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 1000000,
    contract_no: contractNo, start_date: '2026-09-01', end_date: '2027-08-31',
  }, '销售合同')
  const model = await post(request, headers, '/equipment-models',
    { name: `E2E-型号-对账-${RUN}`, category: '大卡', gpu_count: 8 }, '型号')
  const device = await post(request, headers, '/devices', {
    project_id: proj.id, equipment_model_id: model.id, sales_contract_id: contract.id,
    monthly_price: 100000, purchase_value: 960000, ownership: '表内自有',
  }, '设备')
  for (const stage of STAGES) {
    for (const status of ['进行中', '已完成']) {
      const body: any = { stage, status }
      if (stage === '点亮验收' && status === '已完成') body.actual_date = '2026-09-01'
      await post(request, headers, `/devices/${device.id}/stage`, body, `推进${stage}${status}`)
    }
  }
  await post(request, headers, '/billings/device', {
    device_id: device.id, contract_id: contract.id, period_index: 1,
    billing_date: '2026-09-30', idempotency_key: `${device.id}-1`,
  }, '按台计费')
  // 确认收入审批通过
  const recs = await (await request.get(`${API}/revenue-recognitions`, {
    headers, params: { project_id: proj.id },
  })).json()
  await post(request, headers, `/approvals/${recs.items[0].approval_id}/approve`, {}, '确认审批')

  // ---- UI：七维卡渲染 ----
  await uiLogin(page)
  await page.goto('/reconciliation-center')
  await expect(page.getByRole('heading', { name: '对账中心' })).toBeVisible()
  for (const t of ['销售全链路', '采购四单', '资产交付', '监管账户', '汇兑损益', '业财一致性', '三流差异明细']) {
    await expect(page.locator('.n-card', { hasText: t }).first()).toBeVisible()
  }

  // ---- 维度 1：本合同行 flags 正确且整行标红 ----
  const d1Card = page.locator('.n-card', { hasText: '销售全链路' })
  const myRow = d1Card.locator('.n-data-table-tr', { hasText: contractNo })
  await expect(myRow).toBeVisible({ timeout: 8000 })
  await expect(myRow).toContainText('已计未开')
  await expect(myRow).toContainText('已确认未开')
  await expect(myRow).toHaveClass(/diff-row/)

  // ---- 维度 6：注入 3 条模拟差异（验收展示管道）----
  await page.getByTestId('toggle-inject').click()
  const d6Card = page.locator('.n-card', { hasText: '业财一致性' })
  await expect(d6Card.locator('.n-data-table-tr', { hasText: '业财差异' })).toHaveCount(3, { timeout: 8000 })

  // ---- 维度 7：差异明细含本合同 ----
  const d7Card = page.locator('.n-card', { hasText: '三流差异明细' })
  await expect(d7Card.locator('.n-data-table-tr', { hasText: contractNo })).toBeVisible()

  // ---- API 追值：注入后恰好 3 条业财差异 ----
  const d6 = await (await request.get(`${API}/reconciliation-center/ebs-consistency`, {
    headers, params: { inject_demo: true },
  })).json()
  expect(d6.items.filter((i: any) => i.flags.length).length).toBe(3)
  const d6plain = await (await request.get(`${API}/reconciliation-center/ebs-consistency`, { headers })).json()
  expect(d6plain.items.every((i: any) => i.flags.length === 0)).toBe(true) // Mock 默认两端一致
})
