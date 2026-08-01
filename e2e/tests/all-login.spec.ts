import { test, expect } from '@playwright/test'

// 铁证：5 个账号都在真实浏览器里登录成功（密码统一 sie123）
const ACCOUNTS: [string, string][] = [
  ['admin', 'ADMIN'],
  ['cfo', 'FINANCE_DIRECTOR'],
  ['buyer', 'PROCUREMENT'],
  ['delivery', 'DELIVERY'],
  ['finance', 'FINANCE_STAFF'],
]

for (const [u, role] of ACCOUNTS) {
  test(`浏览器登录 ${u}/sie123 → ${role}`, async ({ page, context }) => {
    await context.clearCookies()
    await page.goto('http://localhost:8080/login', { waitUntil: 'networkidle' })
    await page.evaluate(() => localStorage.clear())
    await page.getByPlaceholder('请输入账号').fill(u)
    await page.getByPlaceholder('请输入密码').fill('sie123')
    await page.getByRole('button', { name: /登.*录/ }).click()
    await expect(page).toHaveURL('http://localhost:8080/', { timeout: 8000 })
    // 首页用户区应显示对应角色
    await expect(page.locator('body')).toContainText(role)
  })
}
