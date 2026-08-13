import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 三期 §4.2 收入确认 —— 端到端（端到端铁律）：
//   API 备数（经营租赁/自有项目 + 点亮设备 + 按台计费）→ 确认草稿自动出（不含税 + R1 方法快照）
//   → 科目映射（经营租赁 → 1122.01/6001.01）→ UI 收入确认页草稿可见
//   → 审批中心通过（锚点=项目名）→ UI 状态 已同步EBS → 凭证弹窗追值借贷科目
//   → API 追值：确认单状态/凭证/EBS 出站日志。
// 共享 dev 库无隔离：项目 `E2E-确认-` 前缀，cleanup_e2e 清理（含 mappings/configs 全清与孤儿行兜底）。

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

test('收入确认：计费出草稿 → 审批通过 → Mock 凭证 → 已同步EBS → 追值', async ({ page, request }) => {
  const headers = await apiLogin(request)

  // ---- 备数：R1 项目 + 点亮设备 + 按台计费（自动出草稿）+ 科目映射 ----
  const proj = await post(request, headers, '/projects',
    { name: `E2E-确认-${RUN}`, business_type: '经营租赁', leasing_mode: '自有' }, '立项')
  const cust = await post(request, headers, '/customers', { name: `客户-E2E-确认-${RUN}` }, '客户')
  const model = await post(request, headers, '/equipment-models',
    { name: `E2E-型号-确认-${RUN}`, category: '大卡', gpu_count: 8 }, '型号')
  const contract = await post(request, headers, '/contracts', {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 1000000,
    contract_no: `HT-F${RUN}`, start_date: '2026-09-01', end_date: '2027-08-31',
  }, '销售合同')
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
  const billing = await post(request, headers, '/billings/device', {
    device_id: device.id, contract_id: contract.id, period_index: 1,
    billing_date: '2026-09-30', idempotency_key: `${device.id}-1`,
  }, '按台计费')
  await post(request, headers, '/gl-account-mappings', {
    business_event: '收入确认', revenue_method: '经营租赁',
    debit_account: '1122.01', credit_account: '6001.01',
    description_template: '确认{period}经营租赁收入',
  }, '科目映射')

  // ---- UI：收入确认页草稿可见（项目列锚定本 spec 行，防并发撞同期间同额行）----
  await uiLogin(page)
  await page.goto('/revenue-recognitions')
  await expect(page.getByRole('heading', { name: '收入确认', exact: true })).toBeVisible()
  const row = page.locator('.n-data-table-tr', { hasText: `E2E-确认-${RUN}` })
  await expect(row).toBeVisible({ timeout: 8000 })
  await expect(row).toContainText('草稿')
  await expect(row).toContainText('经营租赁')

  // ---- 审批中心通过（锚点=项目名，防并发撞标题）----
  await page.goto('/payments')
  const tag = page.locator('.n-tag', { hasText: `E2E-确认-${RUN}` })
  await expect(tag).toBeVisible({ timeout: 8000 })
  await tag.getByRole('button', { name: '通过' }).click()
  await expect(page.locator('.n-message', { hasText: '已通过' })).toBeVisible({ timeout: 8000 })

  // ---- UI：行状态 已同步EBS + 点行开凭证弹窗追值 ----
  await page.goto('/revenue-recognitions')
  const myRow = page.locator('.n-data-table-tr', { hasText: `E2E-确认-${RUN}` })
  await expect(myRow).toContainText('已同步EBS', { timeout: 8000 })
  await myRow.click()
  const voucherModal = page.locator('.n-modal').filter({ hasText: 'Mock 凭证' })
  await voucherModal.waitFor()
  await expect(voucherModal).toContainText('1122.01')
  await expect(voucherModal).toContainText('6001.01')
  await expect(voucherModal).toContainText('确认2026-09经营租赁收入')

  // ---- API 追值 ----
  const recs = await (await request.get(`${API}/revenue-recognitions`, {
    headers, params: { project_id: proj.id },
  })).json()
  expect(recs.items.length).toBe(1)
  const rec = recs.items[0]
  expect(rec.status).toBe('已同步EBS')
  expect(Number(rec.amount)).toBeCloseTo(Number(billing.amount_ex_tax), 2) // 权责=不含税
  expect(rec.revenue_method).toBe('经营租赁') // R1 快照
  expect(rec.voucher_json.debit_account).toBe('1122.01')
  const logs = await (await request.get(`${API}/ebs/logs`, {
    headers, params: { entity_type: 'revenue_recognition', limit: 50 },
  })).json()
  const mine = logs.items.filter((l: any) => l.entity_id === rec.id)
  expect(mine.length, '凭证应出站 EBS Mock').toBeGreaterThanOrEqual(1)
  expect(mine[0].status).toBe('MOCK_SUCCESS')
})
