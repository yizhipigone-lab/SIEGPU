import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

// 二期 W5-6 币种与汇率 —— ExchangeRateView 端到端（端到端铁律）：
//   UI 新增币种（E2+RUN 伪码）→ 录入汇率（全精度 8 位小数）→ 试算取值（最近不未来）
//   → 科目规则新增 → API 追值法断言（币种大写归一 / 汇率全精度 / 规则落库）
// 共享 dev 库无隔离：币种码 `E2{RUN}`、场景 `E2E场景-{RUN}`，由 globalTeardown → cleanup_e2e 清理。

const API = '/api'
const RUN = Date.now().toString(36)
const CODE = `E2${RUN}`.toUpperCase().slice(0, 10) // 伪 ISO 码（≤10 字符），真实 ISO 码无 E2 前缀

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

test('币种汇率：新增币种 → 录入汇率 → 试算取值 → 科目规则 → 追值断言', async ({ page, request }) => {
  const headers = await apiLogin(request)
  const today = new Date().toISOString().slice(0, 10)

  await uiLogin(page)
  await page.goto('/exchange-rates')
  await expect(page.getByRole('heading', { name: '币种与汇率' })).toBeVisible()

  // —— ① 新增币种 ——
  await page.getByRole('button', { name: '新增币种' }).click()
  let modal = page.locator('.n-modal').filter({ hasText: '新增币种' })
  await modal.waitFor()
  await modal.locator('.n-form-item', { hasText: '代码' }).locator('input').fill(CODE)
  await modal.locator('.n-form-item', { hasText: '名称' }).locator('input').fill(`E2E测试币${RUN}`)
  await modal.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.n-message', { hasText: '已新增币种' })).toBeVisible({ timeout: 8000 })
  await modal.waitFor({ state: 'hidden', timeout: 15000 }) // 等遮罩退出，防拦截后续点击
  // 币种 tag 区出现（唯一锚点 CODE，禁首行假设）
  await expect(page.locator('.n-tag', { hasText: CODE }).first()).toBeVisible()

  // —— ② 录入汇率（8 位全精度）——
  await page.getByRole('button', { name: '录入汇率' }).click()
  modal = page.locator('.n-modal').filter({ hasText: '录入汇率' })
  await modal.waitFor()
  await modal.getByPlaceholder('如 USD').fill(CODE)
  await modal.getByPlaceholder(/1 外币 = N 元目标币/).fill('7.12345678')
  // 生效日期默认空 → 填今天（n-date-picker 直接键盘输入回车）
  await modal.locator('.n-form-item', { hasText: '生效日期' }).locator('input').fill(today)
  await page.keyboard.press('Enter') // n-date-picker 回车即确认并收面板（不可按 Escape——会连带关弹窗）
  await modal.locator('.n-form-item', { hasText: '来源' }).locator('input').fill('E2E手工')
  await modal.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.n-message', { hasText: '已录入汇率' })).toBeVisible({ timeout: 8000 })
  await modal.waitFor({ state: 'hidden', timeout: 15000 })
  // 汇率表出现该币种对
  await expect(page.locator('.n-data-table', { hasText: `${CODE} → CNY` }).first()).toBeVisible()

  // —— ③ 试算取值（最近不未来）——
  const trialCard = page.locator('.n-card', { hasText: '汇率表' })
  await trialCard.getByPlaceholder('USD').fill(CODE)
  await trialCard.locator('.n-form-item', { hasText: '业务日期' }).locator('input').fill(today)
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  await trialCard.getByRole('button', { name: '取值' }).click()
  const trialResult = page.getByTestId('rate-trial-result')
  await expect(trialResult).toBeVisible({ timeout: 8000 })
  await expect(trialResult).toContainText('7.12345678')

  // —— ④ 科目规则新增（场景带 E2E场景- 前缀，cleanup 按此前缀清）——
  await page.getByRole('button', { name: '新增科目规则' }).click()
  modal = page.locator('.n-modal').filter({ hasText: '新增汇兑损益科目规则' })
  await modal.waitFor()
  await modal.locator('.n-form-item', { hasText: '场景' }).locator('input').fill(`E2E场景-收款核销-${RUN}`)
  await modal.locator('.n-form-item', { hasText: 'EBS 科目码' }).locator('input').fill(`6603.E2E.${RUN}`)
  await modal.locator('.n-form-item', { hasText: '说明' }).locator('input').fill('e2e 验证用')
  await modal.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.n-message', { hasText: '已新增规则' })).toBeVisible({ timeout: 8000 })
  await modal.waitFor({ state: 'hidden', timeout: 15000 })
  await expect(page.locator('.n-data-table', { hasText: `E2E场景-收款核销-${RUN}` }).first()).toBeVisible()

  // —— ⑤ 追值法（API 读回真值）——
  const curs = await (await request.get(`${API}/currencies`, { headers })).json()
  const mine = curs.items.find((c: { code: string }) => c.code === CODE)
  expect(mine, '币种应落库且代码大写归一').toBeTruthy()
  expect(mine.name).toBe(`E2E测试币${RUN}`)

  const rates = await (await request.get(`${API}/exchange-rates`, {
    headers, params: { from_currency: CODE },
  })).json()
  expect(rates.items.length).toBe(1)
  expect(Number(rates.items[0].rate)).toBeCloseTo(7.12345678, 8) // 8 位全精度不截断
  expect(rates.items[0].source).toBe('E2E手工')

  // lookup 端点：同币种恒 1（不查表）
  const same = await (await request.get(`${API}/exchange-rates/lookup`, {
    headers, params: { from_currency: CODE, to_currency: CODE, on_date: today },
  })).json()
  expect(Number(same.rate)).toBe(1)
})
