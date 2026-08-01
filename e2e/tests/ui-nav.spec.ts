import { test, expect } from '@playwright/test'

// 验证新前端业务页面可导航且渲染正常
test('UI 导航：资金池页 + 主数据页', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('cfo123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/)

  // 资金池旗舰页
  await page.goto('/capital')
  await expect(page.getByText('资金池余额')).toBeVisible()
  await expect(page.getByText('资金流水')).toBeVisible()

  // 主数据通用 CRUD 页
  await page.goto('/master/suppliers')
  await expect(page.getByRole('heading', { name: '供应商' })).toBeVisible()
  await expect(page.getByRole('button', { name: '新增' })).toBeVisible()
})
