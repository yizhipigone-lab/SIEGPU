import { test, expect, type APIRequestContext, type Page, type Locator } from '@playwright/test'
import { execSync } from 'child_process'
import * as path from 'path'

// 一期终审 W9：给 4 个已实现但缺正向 e2e 覆盖的功能补端到端 journey（端到端铁律）。
//   F4 合同/发票 PDF —— 点 PDF 按钮 → 浏览器下载 → 读首字节验 %PDF（合同走 GenericCrud 图标按钮 + 发票走 InvoicesView 文字按钮，两条前端入口各覆盖一条）
//   F2 设备可租看板 —— 点亮一台表内自有设备 → API 聚合 available>=1（追值法）→ UI 看板含该型号
//   F3 客户对账单  —— 造客户+销售合同 → API 四 KPI 勾稽（追值法）→ UI 选客户看「未计费」金额回传
//   F1 消息提醒铃铛 —— cfo 有未读 → 红点 → 点开列表 → 全部已读 → 红点消失（scan_and_persist 由 9 条单测覆盖，e2e 聚焦前端铃铛交互，数据用 docker exec 直插保证确定性）
// 共享 dev 库无测试隔离：每场景用 RUN 派生唯一数据隔离自身。

const API = '/api'
const RUN = Date.now().toString(36)
// docker-compose.yml 在仓库根；e2e/tests -> ../.. 。F1 用它 exec 进 backend 容器。
const REPO = path.resolve(__dirname, '..', '..')

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

// ---- naive-ui n-select 三坑收敛助手（镜像 w7_8：placeholder 不在 input / 残留隐藏 option / 过渡动画时序）----
async function waitForMenu(page: Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}

// ---- API 推进单台设备到点亮验收（上架派生表内自有；点亮激活运营）----
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

// 读下载流首字节，验 %PDF 魔数（PDF 真伪的零依赖判据）。
async function readPdfHead(download: { createReadStream: () => Promise<NodeJS.ReadableStream> }): Promise<string> {
  const stream = await download.createReadStream()
  return new Promise<string>((resolve) => {
    let done = false
    stream.on('data', (chunk: Buffer) => {
      if (!done) { done = true; resolve(chunk.toString('latin1').slice(0, 5)); stream.destroy() }
    })
    stream.on('end', () => { if (!done) resolve('') })
    stream.on('error', () => { if (!done) resolve('') })
  })
}

// ============ F4 合同/发票 PDF 下载 ============
test('F4 合同/发票 PDF：点按钮 → 浏览器下载真实 PDF（%PDF 头）', async ({ page, request }) => {
  const headers = await apiLogin(request)
  // 备数：项目 + 客户 + 销售合同(RUN 合同号) + 发票(RUN 发票号)
  const proj = await (await request.post(`${API}/projects`, { headers, data: { name: `E2E-F4-${RUN}` } })).json()
  const cust = await (await request.post(`${API}/customers`, { headers, data: { name: `客户-F4-${RUN}` } })).json()
  const contractNo = `HT-F4-${RUN}`
  const contract = await (await request.post(`${API}/contracts`, { headers, data: {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 1234567, contract_no: contractNo,
  } })).json()
  const invoiceNo = `INV-F4-${RUN}`
  const inv = await (await request.post(`${API}/invoices`, { headers, data: {
    contract_id: contract.id, amount: 999999, invoice_no: invoiceNo,
    issue_date: '2026-01-10', due_date: '2026-02-10',
  } })).json()
  expect(inv.invoice_no).toBe(invoiceNo)

  await uiLogin(page)

  // —— ① 合同 PDF（GenericCrud 图标按钮，title=导出PDF）。搜索框收窄到本合同绕开分页 ——
  await page.goto('/master/contracts')
  await page.getByPlaceholder(/搜索/).fill(contractNo)
  const cRow = page.locator('.n-data-table tbody tr').filter({ hasText: contractNo })
  await expect(cRow).toBeVisible({ timeout: 10000 })
  const cDlPromise = page.waitForEvent('download')
  await cRow.locator('button[title="导出PDF"]').click()
  const cDl = await cDlPromise
  expect((await readPdfHead(cDl)).startsWith('%PDF')).toBeTruthy()
  expect(cDl.suggestedFilename()).toMatch(/\.pdf$/)

  // —— ② 发票 PDF（InvoicesView 文字按钮 'PDF'；无分页，全行在 DOM）——
  await page.goto('/invoices')
  const iRow = page.locator('.n-data-table tbody tr').filter({ hasText: invoiceNo })
  await expect(iRow).toBeVisible({ timeout: 10000 })
  const iDlPromise = page.waitForEvent('download')
  await iRow.getByRole('button', { name: 'PDF', exact: true }).click()
  const iDl = await iDlPromise
  expect((await readPdfHead(iDl)).startsWith('%PDF')).toBeTruthy()
  expect(iDl.suggestedFilename()).toMatch(/\.pdf$/)
})

// ============ F2 设备可租库存看板 ============
test('F2 设备可租看板：点亮表内自有设备 → 看板该型号 available>=1（追值法）', async ({ page, request }) => {
  test.slow() // 14 轮 API 推进
  const headers = await apiLogin(request)
  const sn = `GPU-F2-${RUN}`
  const modelName = `M-F2-${RUN}`
  const proj = await (await request.post(`${API}/projects`, { headers, data: { name: `E2E-F2-${RUN}` } })).json()
  const eq = await (await request.post(`${API}/equipment-models`, {
    headers, data: { name: modelName, category: '大卡', gpu_count: 8 },
  })).json()
  const dev = await (await request.post(`${API}/devices`, {
    headers, data: { sn, project_id: proj.id, equipment_model_id: eq.id, leasing_mode: '自有', purchase_value: 1000000 },
  })).json()
  await advanceToLit(request, headers, dev.id, '2026-01-15') // 上架→表内自有；点亮→可租（无计费单）

  // 追值法：API 聚合该型号 available>=1
  const inv = await (await request.get(`${API}/devices/inventory-summary`, { headers })).json()
  const row = inv.items.find((r: any) => r.model_name === modelName)
  expect(row, `看板未含型号 ${modelName}`).toBeTruthy()
  expect(row.available).toBeGreaterThanOrEqual(1)

  // UI：可租库存卡含该型号 + 三口径标签
  await uiLogin(page)
  await page.goto('/devices')
  await expect(page.getByRole('heading', { name: '设备清单' })).toBeVisible()
  const card = page.locator('.n-card', { hasText: '可租库存' })
  await expect(card).toBeVisible()
  await expect(card.locator('.n-data-table tbody tr').filter({ hasText: modelName })).toBeVisible()
  await expect(card.locator('.inv-lbl', { hasText: '可租' })).toBeVisible()
})

// ============ F3 客户对账单 ============
test('F3 客户对账单：造客户+合同 → 四 KPI 勾稽（追值法）→ UI 选客户回传未计费额', async ({ page, request }) => {
  const headers = await apiLogin(request)
  const custName = `客户-F3-${RUN}`
  const cust = await (await request.post(`${API}/customers`, { headers, data: { name: custName } })).json()
  const proj = await (await request.post(`${API}/projects`, { headers, data: { name: `E2E-F3-${RUN}` } })).json()
  await request.post(`${API}/contracts`, { headers, data: {
    project_id: proj.id, type: 'SALES', party_id: cust.id, amount: 2000000, contract_no: `HT-F3-${RUN}`,
  } })

  // 追值法：API 对账单四值（无计费/开票/回款 → 全 0，未计费=合同额）。q2 经 JSON 序列化为数值，用 Number() 兜底
  const st = await (await request.get(`${API}/reports/customer-statement?customer_id=${cust.id}`, { headers })).json()
  expect(Number(st.contract_amount)).toBe(2000000)
  expect(Number(st.billed)).toBe(0)
  expect(Number(st.invoiced)).toBe(0)
  expect(Number(st.received)).toBe(0)
  expect(Number(st.gap_unbilled)).toBe(2000000)

  // UI：选客户 → 客户名 + 四 KPI + 未计费金额回传
  await uiLogin(page)
  await page.goto('/customer-statement')
  await expect(page.getByRole('heading', { name: '客户对账单' })).toBeVisible()
  const picker = page.locator('.cs-picker')
  await picker.click()
  await waitForMenu(page, true)
  await picker.locator('input').fill(custName)
  await page.waitForTimeout(250) // 等 naive-ui 过滤收窄
  await page.locator('.n-base-select-option').filter({ visible: true }).first().click()
  await waitForMenu(page, false)

  await expect(page.locator('.n-statistic', { hasText: '合同额(不含税)' })).toBeVisible()
  await expect(page.locator('.n-statistic', { hasText: '已回款' })).toBeVisible()
  // 追值法 UI：未计费 <b>{{ money(gap_unbilled) }}</b> = 2,000,000.00（money() 千分位+两位小数）
  await expect(page.locator('b', { hasText: '2,000,000.00' })).toBeVisible()
})

// ============ F1 消息提醒铃铛 ============
test('F1 消息提醒铃铛：未读红点 → 点开列表 → 全部已读 → 红点消失', async ({ page, request }) => {
  test.slow() // docker exec + 30s 轮询
  const headers = await apiLogin(request)
  const token = `E2E-F1-${RUN}`
  // scan_and_persist 的扇出/去重/隔离由 9 条单测覆盖；e2e 聚焦前端铃铛交互。
  // 用 docker exec 直插一条 RUN 唯一通知给 cfo（先清旧 → 确定未读=1）。
  // python 走 stdin（python -），规避 shell 引号；脚本只含单引号，shell 命令本身无引号。
  const py = [
    'from app.core.db import SessionLocal',
    'from app.models.user import User',
    'from app.models.notification import Notification',
    'db = SessionLocal()',
    "u = db.query(User).filter(User.username == 'cfo').first()",
    'db.query(Notification).filter(Notification.user_id == u.id).delete()',
    `db.add(Notification(user_id=u.id, kind='REPAYMENT_OVERDUE', ref_type='capital', ref_id=None, title='还款逾期', body='${token} 测试提醒', level='高危'))`,
    'db.commit()',
  ].join('\n')
  execSync('docker compose exec -T backend python -', {
    cwd: REPO, input: py, stdio: ['pipe', 'ignore', 'inherit'],
  })

  await uiLogin(page, 'cfo')
  await page.goto('/') // MainLayout 挂载 → fetchNotifs 拉未读

  // 红点出现（未读=1）。限到顶栏，避免误匹 Dashboard 的其它 badge。
  // 注意：naive-ui NBadge 用「老虎机」数字动画（SlotMachineNumber），每个数字位在 DOM 里
  // 渲染 3 份（old-top/current/old-bottom）做滚动效果，CSS 只露 current 一份，但 textContent
  // 会拼成 "111"。故不读 sup 文本，改读 title 属性——它走 getTitleAttribute(value)，是绑定的真值。
  const bellSup = page.locator('.n-layout-header .n-badge-sup')
  await expect(bellSup).toBeVisible({ timeout: 8000 })
  await expect(bellSup).toHaveAttribute('title', '1')

  // 点铃铛 → popover 列表含本条 + 「全部已读」
  await page.getByRole('button', { name: '消息提醒' }).click()
  await expect(page.getByText(`${token} 测试提醒`)).toBeVisible()
  await expect(page.getByRole('button', { name: '全部已读' })).toBeVisible()

  // 全部已读 → 红点消失（:show="unreadCount > 0" 为 false 时 sup 不渲染/隐藏）
  await page.getByRole('button', { name: '全部已读' }).click()
  await expect(bellSup).toBeHidden({ timeout: 5000 })

  // 追值法：API 确认 cfo unread=0
  const after = await (await request.get(`${API}/notifications`, { headers })).json()
  expect(after.unread_count).toBe(0)
})
