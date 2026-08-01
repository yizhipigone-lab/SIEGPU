import { test } from '@playwright/test'

// 视觉验证：截取关键页面，便于人工/AI 复核新设计系统落地效果
test('截图关键页面', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/login')
  await page.waitForTimeout(600)
  await page.screenshot({ path: 'screenshots/login.png' })

  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('cfo123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await page.waitForURL('/')

  await page.goto('/'); await page.waitForTimeout(1800)
  await page.screenshot({ path: 'screenshots/home.png', fullPage: true })

  await page.goto('/capital'); await page.waitForTimeout(1800)
  await page.screenshot({ path: 'screenshots/capital.png', fullPage: true })

  await page.goto('/invoices'); await page.waitForTimeout(1200)
  await page.screenshot({ path: 'screenshots/invoices.png', fullPage: true })

  await page.goto('/master/suppliers'); await page.waitForTimeout(1000)
  await page.screenshot({ path: 'screenshots/master.png', fullPage: true })
})
