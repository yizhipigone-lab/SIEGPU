import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 三期 §4.4 采购退货 —— 端到端（端到端铁律）：
//   API 备数（采购合同 + 2 台到货设备 + 采购发票）→ UI 新增退货（2 台，金额=Σ原值 100 万）
//   → 详情抽屉逐步推进：出库确认（设备已退货）→ 供应商收货 → 开红字发票 → 退款核销
//   → API 追值：设备状态/红票红冲关联/退款流水/核销行/退货单终态。
// 共享 dev 库无隔离：项目 E2E- 前缀；红字发票 `红字-` 前缀；孤儿行 cleanup 兜底。

const API = '/api'
const RUN = Date.now().toString(36)

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

test('退货：UI 申请 → 逐步推进到退款核销 → 全链追值', async ({ page, request }) => {
  const headers = await apiLogin(request)

  // ---- 备数：项目 + 供应商 + 采购合同 + 2 台到货设备（60万/40万）+ 采购发票 ----
  const proj = await post(request, headers, '/projects', { name: `E2E-退货-${RUN}` }, '立项')
  const sup = await post(request, headers, '/suppliers',
    { name: `E2E供应商-退货-${RUN}`, type: '设备供应商' }, '供应商')
  const contract = await post(request, headers, '/contracts', {
    project_id: proj.id, type: 'PURCHASE', party_id: sup.id, amount: 10000000,
  }, '采购合同')
  const model = await post(request, headers, '/equipment-models',
    { name: `E2E-型号-退货-${RUN}`, category: '大卡', gpu_count: 8 }, '型号')
  const devices: any[] = []
  for (const pv of [600000, 400000]) {
    const d = await post(request, headers, '/devices', {
      project_id: proj.id, equipment_model_id: model.id, purchase_value: pv, ownership: '表内自有',
    }, '设备')
    for (const stage of ['订货', '在途', '到货']) {
      for (const status of ['进行中', '已完成']) {
        await post(request, headers, `/devices/${d.id}/stage`, { stage, status }, `推进${stage}${status}`)
      }
    }
    devices.push(d)
  }
  const invoice = await post(request, headers, '/invoices', {
    contract_id: contract.id, amount: 1000000, invoice_no: `INV-E2E-退-${RUN}`, issue_date: '2026-08-01',
  }, '采购发票')

  // ---- UI：新增退货 ----
  await uiLogin(page)
  await page.goto('/returns')
  await expect(page.getByRole('heading', { name: '退货管理' })).toBeVisible()
  await page.getByRole('button', { name: '新增退货' }).click()
  const modal = page.locator('.n-modal').filter({ hasText: '新增退货' })
  await modal.waitFor()
  const projItem = modal.locator('.n-form-item', { hasText: '选择项目' })
  await projItem.locator('.n-base-selection').click()
  await page.waitForTimeout(300)
  await projItem.locator('input').fill(`E2E-退货-${RUN}`)
  await page.waitForTimeout(400)
  await page.locator('.n-base-select-option', { hasText: `E2E-退货-${RUN}` }).filter({ visible: true }).first().click()
  for (const d of devices) {
    const sel = modal.getByTestId('return-devices')
    await sel.click()
    await page.waitForTimeout(300)
    await sel.locator('input').fill(d.sn)
    await page.waitForTimeout(400)
    await page.locator('.n-base-select-option', { hasText: d.sn }).filter({ visible: true }).first().click()
  }
  // 收多选菜单（焦点在多选 input 内按 Escape 只收菜单；先判开着才按）
  if (await page.locator('.n-base-select-menu').filter({ visible: true }).count() > 0) {
    await modal.getByTestId('return-devices').locator('input').press('Escape')
    await page.waitForTimeout(300)
  }
  await modal.locator('.n-form-item', { hasText: '原因' }).locator('input').fill(`E2E退货-${RUN}`)
  await modal.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.n-message', { hasText: '退货申请已创建' })).toBeVisible({ timeout: 8000 })
  await modal.waitFor({ state: 'hidden', timeout: 15000 })

  // ---- 详情抽屉：金额 100 万 + 逐步推进 ----
  const row = page.locator('.n-data-table-tr', { hasText: '到货不合格' }).filter({ hasText: '1,000,000.00' }).first()
  await expect(row).toBeVisible()
  await row.click()
  const drawer = page.locator('.n-drawer')
  await drawer.waitFor()
  await expect(drawer).toContainText('1,000,000.00')
  for (const step of ['出库确认', '供应商收货', '开红字发票', '退款核销']) {
    await drawer.getByTestId('return-advance').click()
    // 断言带步骤名的消息（前序消息残留在页面，裸「已推进」会撞 strict mode）
    await expect(page.locator('.n-message', { hasText: `已推进：${step} 完成` }).last()).toBeVisible({ timeout: 8000 })
    await expect(drawer).toContainText(step === '退款核销' ? '已退款核销' : step === '开红字发票' ? '已开红字发票' : step === '供应商收货' ? '供应商已收货' : '已出库', { timeout: 8000 })
  }
  await expect(drawer).toContainText('已到终态')

  // ---- API 追值 ----
  for (const d of devices) {
    const devs = await (await request.get(`${API}/devices`, { headers, params: { project_id: proj.id } })).json()
    expect(devs.items.find((x: any) => x.id === d.id).status).toBe('已退货')
  }
  const rets = await (await request.get(`${API}/returns`, { headers, params: { project_id: proj.id } })).json()
  const ro = rets.items[0]
  expect(ro.status).toBe('已退款核销')
  expect(Number(ro.total_amount)).toBe(1000000)
  expect(ro.red_invoice_id).toBeTruthy()
  expect(ro.refund_txn_id).toBeTruthy()
  const redInv = (await (await request.get(`${API}/invoices/pool`, { headers })).json())
    .items.find((i: any) => i.id === ro.red_invoice_id)
  expect(redInv.amount).toBe('1000000.00')
  const setts = await (await request.get(`${API}/payment-settlements`, {
    headers, params: { invoice_id: ro.red_invoice_id },
  })).json()
  expect(setts.items.length).toBe(1)
  expect(Number(setts.items[0].amount)).toBe(1000000)
})
