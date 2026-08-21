import { test, expect, type Page, type APIRequestContext } from '@playwright/test'

// 设备粒度向导模板（device-flow-7stage）端到端走查（一期 W3-4 B2，W7-8 增至 11 步）：
//   1. 选 device-flow 模板建项目 → 后端生成 11 步设备粒度工作流（非 18 步旧模板）
//   2. 工作台 UI 渲染 11 步 + 设备专属步骤标题（设备导入/设备到货/点亮验收）
//   3. API 推进设备「到货」节点 → Step6「设备到货」翻绿（证明 completion_check 真查 device_stages，
//      而非旧 delivery_stages；与后端 test_device_flow_step6 的 D6 跨项目回归互补）
// 串行：测试 3 依赖测试 1 建好的项目与主数据。
test.describe.configure({ mode: 'serial' })

const api = '/api'
const RUN = Date.now().toString(36)
const projectName = `E2E-设备流-${RUN}`

let projectId = ''
let headers: Record<string, string>

async function apiLogin(request: APIRequestContext, username: string, password = 'sie123') {
  const res = await request.post(`${api}/auth/login`, { form: { username, password } })
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

test('1. 准备数据：选 device-flow 模板建项目（11 步工作流）', async ({ request }) => {
  headers = await apiLogin(request, 'cfo')

  // 主数据
  const sup = await request.post(`${api}/suppliers`, { headers, data: { name: `E2E供应商-${RUN}`, type: '设备供应商' } })
  expect(sup.ok()).toBeTruthy()
  const cus = await request.post(`${api}/customers`, { headers, data: { name: `E2E客户-${RUN}` } })
  expect(cus.ok()).toBeTruthy()
  const eq = await request.post(`${api}/equipment-models`, {
    headers, data: { name: `E2E-H100-${RUN}`, category: '大卡', gpu_count: 8 },
  })
  expect(eq.ok()).toBeTruthy()

  // 找 device-flow 模板（seed 名「设备粒度流程（10步·device-flow-7stage）」，W7-8 起 11 步）
  const tplRes = await request.get(`${api}/workflows/templates`, { headers })
  expect(tplRes.ok()).toBeTruthy()
  const templates = await tplRes.json()
  const tpl = templates.find((t: { name: string }) => t.name.includes('device-flow') || t.name.includes('设备粒度'))
  expect(tpl, '未找到 device-flow 模板（seed_templates 是否执行？)').toBeTruthy()

  // 建项目（带 template_id）→ 后端按设备粒度模板生成工作流
  const proj = await request.post(`${api}/projects`, { headers, data: { name: projectName, template_id: tpl.id } })
  expect(proj.ok()).toBeTruthy()
  projectId = (await proj.json()).id
  expect(projectId).toBeTruthy()

  const wf = await (await request.get(`${api}/workflows/${projectId}`, { headers })).json()
  expect(wf.steps.length).toBe(11)           // 设备粒度 11 步（W7-8 增金租放款），非旧 18 步
  expect(wf.current_step).toBe(2)            // Step1 项目建立自动完成
  const titles = wf.steps.map((s: { name: string }) => s.name)
  expect(titles).toContain('设备导入')
  expect(titles).toContain('设备到货')
  expect(titles).toContain('点亮验收')

  ;(globalThis as any).__df = {
    supplierId: (await sup.json()).id,
    customerId: (await cus.json()).id,
    equipId: (await eq.json()).id,
  }
})

test('2. 工作台渲染设备粒度 11 步模板', async ({ page }) => {
  await uiLogin(page, 'buyer')
  await page.goto(`/projects/${projectId}/workspace`)

  // Step1 自动完成 → 1/11
  await expect(page.getByText('1 / 11 步完成')).toBeVisible()
  // 当前步骤 = Step 2 销售合同（与旧模板同名，但总步数 11 证明是设备模板）
  await expect(page.locator('.n-card', { hasText: '当前' })).toContainText('Step 2 — 销售合同')
  // 设备专属步骤标题渲染出来（旧 18 步模板无「设备导入」）
  await expect(page.getByText('设备导入')).toBeVisible()
  await expect(page.getByText('设备到货')).toBeVisible()
})

test('3. 设备推进到货 → Step6「设备到货」翻绿（completion_check 真查 device_stages）', async ({ page, request }) => {
  const { supplierId, customerId, equipId } = (globalThis as any).__df
  const post = (url: string, data: Record<string, unknown>) => request.post(`${api}${url}`, { headers, data })

  // 链式备数：Step2 销售合同 / Step3 采购合同 / Step4 批次订单(is_batch) / Step5 设备导入
  const sc = await post('/contracts', { project_id: projectId, type: 'SALES', party_id: customerId,
    amount: 5_000_000, start_date: '2026-01-01', end_date: '2028-12-31' })
  expect(sc.ok()).toBeTruthy()
  const pc = await post('/contracts', { project_id: projectId, type: 'PURCHASE', party_id: supplierId,
    amount: 4_000_000, start_date: '2026-01-01', end_date: '2026-12-31',
    parent_contract_id: (await sc.json()).id })  // 硬校验：采购合同必须参照同项目销售合同
  expect(pc.ok()).toBeTruthy()
  // 批次订单：schema 仍要求 equipment_model_id/quantity/unit_price（service 的 is_batch 分支忽略其语义）
  // 自检迭代：断言响应体吐真值 is_batch=true / flow_type='batch'（修正前 create_order 手工构造漏字段→说谎 is_batch=false）
  const orderRes = await post('/orders', { project_id: projectId, contract_id: (await pc.json()).id,
    equipment_model_id: equipId, quantity: 10, unit_price: 400_000, is_batch: true })
  expect(orderRes.ok()).toBeTruthy()
  const orderBody = await orderRes.json()
  expect(orderBody.is_batch).toBe(true)
  expect(orderBody.flow_type).toBe('batch')
  const dev = await post('/devices', { project_id: projectId, equipment_model_id: equipId })
  expect(dev.ok()).toBeTruthy()
  const deviceId = (await dev.json()).id

  // Step6 设备到货：device_stages stage=到货 status=已完成（到货行 未开始→进行中→已完成，两跳）
  expect((await post(`/devices/${deviceId}/stage`, { stage: '到货', status: '进行中' })).ok()).toBeTruthy()
  expect((await post(`/devices/${deviceId}/stage`, { stage: '到货', status: '已完成' })).ok()).toBeTruthy()

  // 刷新工作流 → Step1-6 全完成，current_step=7（设备上架）
  const refRes = await request.post(`${api}/workflows/${projectId}/refresh`, { headers })
  expect(refRes.ok()).toBeTruthy()
  expect((await refRes.json()).current_step).toBe(7)

  // UI：进度由 1/11 → 6/11，当前步骤推进到 Step 7 设备上架
  await uiLogin(page, 'cfo')
  await page.goto(`/projects/${projectId}/workspace`)
  await expect(page.getByText('6 / 11 步完成')).toBeVisible()
  await expect(page.locator('.n-card', { hasText: '当前' })).toContainText('Step 7 — 设备上架')
  // 「设备到货」步骤已亮绿（已完成 tag 计数 ≥6）
  await expect(page.locator('.n-tag', { hasText: '已完成' })).toHaveCount(6)
})
