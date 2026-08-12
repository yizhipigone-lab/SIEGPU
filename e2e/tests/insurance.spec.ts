import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 二期 W7-8 保险管理 —— InsuranceView 端到端（端到端铁律）：
//   API 备数（项目 + 2 台设备推进到上架建卡）→ UI 新增保单（保额×费率 → 保费预览）
//   → 详情抽屉设备分摊（60万/40万 → 600/400 追值）→ 确认生效 → 归集进原值（点亮前窗口）
//   → API 追值：保单分摊 + 资产原值精确累加。
// 共享 dev 库无隔离：项目 `E2E-保险-` 前缀、型号 `E2E-` 前缀、设备 SN `GPU-` 自动前缀，
// 保单/资产靠 project_id 级联清，分摊孤儿行由 cleanup_e2e 兜底扫除。

const API = '/api'
const RUN = Date.now().toString(36)
const PRE_LIT_STAGES = ['订货', '在途', '到货', '己方压测', '上架'] // 推进到上架建卡（点亮前窗口）

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

test('保险：UI 录保单 → 设备分摊追值 → 确认生效 → 归集进原值（点亮前）', async ({ page, request }) => {
  const headers = await apiLogin(request)

  // ---- 备数：项目 + 型号 + 2 台设备（60万/40万），推进到上架（建资产卡，点亮前窗口）----
  const proj = await (await request.post(`${API}/projects`, {
    headers, data: { name: `E2E-保险-${RUN}` },
  })).json()
  const model = await (await request.post(`${API}/equipment-models`, {
    headers, data: { name: `E2E-型号-保险-${RUN}`, category: '大卡', gpu_count: 8 },
  })).json()
  const devices: any[] = []
  for (const pv of [600000, 400000]) {
    const d = await (await request.post(`${API}/devices`, {
      headers, data: { project_id: proj.id, equipment_model_id: model.id, purchase_value: pv, ownership: '表内自有' },
    })).json()
    expect(d.id).toBeTruthy()
    for (const stage of PRE_LIT_STAGES) {
      for (const status of ['进行中', '已完成']) {
        const r = await request.post(`${API}/devices/${d.id}/stage`, { headers, data: { stage, status } })
        expect(r.ok(), `advance ${stage}/${status}: ${await r.text()}`).toBeTruthy()
      }
    }
    devices.push(d)
  }

  // ---- UI：新增保单 ----
  await uiLogin(page)
  await page.goto('/insurance')
  await expect(page.getByRole('heading', { name: '保险管理' })).toBeVisible()
  await page.getByRole('button', { name: '新增保单' }).click()
  const modal = page.locator('.n-modal').filter({ hasText: '新增保单' })
  await modal.waitFor()

  // 项目（远程下拉：键入收窄再点，并发慢库稳妥手法；用 placeholder「选择项目」定位，防撞「覆盖设备」的提示文案）
  const projItem = modal.locator('.n-form-item', { hasText: '选择项目' })
  await projItem.locator('.n-base-selection').click()
  await page.waitForTimeout(300)
  await projItem.locator('input').fill(`E2E-保险-${RUN}`)
  await page.waitForTimeout(400)
  await page.locator('.n-base-select-option', { hasText: `E2E-保险-${RUN}` }).filter({ visible: true }).first().click()

  // 险种：财产险
  await modal.locator('.n-form-item', { hasText: '险种' }).locator('.n-base-selection').click()
  await page.locator('.n-base-select-option', { hasText: '财产险' }).filter({ visible: true }).first().click()

  // 先填保额/费率（此时无下拉菜单遮挡），blur 后 NInputNumber 才同步 v-model → 再看保费预览
  await modal.locator('.n-form-item', { hasText: '保额' }).locator('input').fill('1000000')
  await modal.locator('.n-form-item', { hasText: '费率' }).locator('input').fill('0.001')
  await modal.locator('.n-form-item', { hasText: '保单号' }).locator('input').click() // 触发 blur 同步
  await expect(modal).toContainText('保费预览：1000.00')
  await modal.locator('.n-form-item', { hasText: '归集口径' }).locator('.n-base-selection').click()
  await page.locator('.n-base-select-option', { hasText: '资产原值' }).filter({ visible: true }).first().click()

  // 覆盖设备（多选：逐台键入 SN 收窄点选；最后点「保单号」输入框收菜单——不可 Escape，会连关弹窗）
  for (const d of devices) {
    const sel = modal.getByTestId('policy-devices')
    await sel.click()
    await page.waitForTimeout(300)
    await sel.locator('input').fill(d.sn)
    await page.waitForTimeout(400)
    await page.locator('.n-base-select-option', { hasText: d.sn }).filter({ visible: true }).first().click()
  }
  // 收多选菜单：焦点在多选 input 内按 Escape 只收菜单；先判菜单开着才按（防菜单已关时 Escape 误关弹窗）。
  // （不可点其他输入框收——菜单向下展开恰好盖住下方输入框，点击会被菜单 option 拦截）
  if (await page.locator('.n-base-select-menu').filter({ visible: true }).count() > 0) {
    await modal.getByTestId('policy-devices').locator('input').press('Escape')
    await page.waitForTimeout(300)
  }
  await modal.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.n-message', { hasText: '保单已创建' })).toBeVisible({ timeout: 8000 })
  await modal.waitFor({ state: 'hidden', timeout: 15000 }) // 等遮罩退出防拦截

  // ---- 详情抽屉：设备分摊追值（600/400）----
  // 唯一锚点「手工」（本 spec 手工录单；并发下 phase2-chain 的财产险触发=点亮，禁裸 .first() 首行假设）
  const row = page.locator('.n-data-table-tr', { hasText: '财产险' }).filter({ hasText: '手工' }).first()
  await expect(row).toBeVisible()
  await row.click()
  const drawer = page.locator('.n-drawer')
  await drawer.waitFor()
  for (const [d, share] of [[devices[0], '600.00'], [devices[1], '400.00']] as const) {
    const devRow = drawer.locator('.n-data-table-tr', { hasText: d.sn })
    await expect(devRow).toContainText(share)
  }

  // ---- 确认生效 → 归集进原值 ----
  await drawer.getByRole('button', { name: '确认生效' }).click()
  await expect(page.locator('.n-message', { hasText: '已确认生效' })).toBeVisible({ timeout: 8000 })
  await drawer.getByRole('button', { name: '归集进原值' }).click()
  await expect(page.locator('.n-message', { hasText: '归集进资产原值' })).toBeVisible({ timeout: 8000 })
  await expect(drawer).toContainText('已归集进原值')

  // ---- API 追值：保单分摊 + 资产原值精确累加 ----
  const pols = await (await request.get(`${API}/insurance/policies`, {
    headers, params: { project_id: proj.id },
  })).json()
  expect(pols.items.length).toBe(1)
  const pol = pols.items[0]
  expect(Number(pol.premium_amount)).toBe(1000)
  expect(pol.status).toBe('已生效')
  expect(pol.collected_at).toBeTruthy()

  const assets = await (await request.get(`${API}/assets`, {
    headers, params: { project_id: proj.id },
  })).json()
  const byDevice = Object.fromEntries((assets.items || assets).map((a: any) => [a.device_id, a]))
  expect(Number(byDevice[devices[0].id].total_original_value)).toBe(600600) // 600000 + 600
  expect(Number(byDevice[devices[1].id].total_original_value)).toBe(400400) // 400000 + 400
})
