import { test, expect, type Page } from '@playwright/test'

// 三期 §4.5 经营看板 —— 端到端（端到端铁律）：
//   cfo 登录 → 首页经营看板区渲染（8 核心指标 + 待办中心 + 资金预测 3 行 + EBS 状态卡）
//   → 「待处理」卡/角色首页不受影响（零回归由 wizard-workspace 等存量 spec 守）。
// 不造数：结构断言 + API 追值（business 端点四块齐全）。

const API = '/api'

async function uiLogin(page: Page, username = 'cfo') {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill(username)
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/, { timeout: 8000 })
}

test('经营看板：首页四块渲染 + API 结构追值', async ({ page, request }) => {
  await uiLogin(page)
  await page.goto('/')

  const board = page.getByTestId('business-board')
  await expect(board).toBeVisible({ timeout: 10000 })
  for (const label of ['当期合同额', '累计回款', '开票金额', '确认收入', '融资余额', '资金池余额', '监管账户余额', '设备交付进度']) {
    await expect(board).toContainText(label)
  }
  // 待办中心
  const todo = page.getByTestId('todo-center')
  await expect(todo).toBeVisible()
  await expect(todo).toContainText('付款/收入审批')
  await expect(todo).toContainText('预付款未结清设备')
  // 资金预测：3 行（未来 3 个月）
  const forecastCard = page.locator('.n-card', { hasText: '资金预测概览' })
  await expect(forecastCard.locator('.n-data-table-tbody .n-data-table-tr')).toHaveCount(3)
  // EBS 状态卡
  await expect(page.locator('.n-card', { hasText: 'EBS 同步状态' })).toContainText('成功')

  // API 追值：四块齐全 + 预测 3 期滚动
  const res = await request.post(`${API}/auth/login`, { form: { username: 'cfo', password: 'sie123' } })
  const { access_token } = await res.json()
  const headers = { Authorization: `Bearer ${access_token}` }
  const data = await (await request.get(`${API}/dashboard/business`, { headers })).json()
  expect(Object.keys(data.metrics)).toContain('supervised_balance')
  expect(data.todo_center.length).toBeGreaterThanOrEqual(6)
  expect(data.forecast.length).toBe(3)
  expect(data.forecast[1].opening).toBe(data.forecast[0].closing) // 滚动衔接
  expect(data.ebs).toHaveProperty('success')
})
