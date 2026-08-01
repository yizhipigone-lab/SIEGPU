import { test, expect } from '@playwright/test'

// 真实浏览器 UI 登录流程（需要 chromium 已安装）
test('浏览器登录 → 仪表盘', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('项目概览')).toBeVisible()
})
