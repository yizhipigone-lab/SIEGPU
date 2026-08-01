import { test } from '@playwright/test'
import * as fs from 'fs'
test('合同详情抽屉 + 上传', async ({ page }) => {
  await page.goto('http://localhost:9000/login', { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入账号"]', 'cfo')
  await page.fill('input[placeholder="请输入密码"]', 'sie123')
  await page.click('button:has-text("登")')
  await page.waitForTimeout(1500)
  await page.goto('http://localhost:9000/master/contracts', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1000)
  // 点眼睛图标（详情）
  const eyeBtn = page.locator('button[title="详情"]').first()
  if (await eyeBtn.count()) {
    await eyeBtn.click()
    await page.waitForTimeout(800)
    const drawerText = await page.locator('.n-drawer-content').innerText().catch(() => '?')
    fs.writeFileSync('drawer-text.txt', drawerText.slice(0, 500))
    console.log('DRAWER OPEN:', drawerText.includes('附件') ? '有附件区' : '无附件区', drawerText.includes('上传') ? '有上传按钮' : '无上传')
  } else {
    console.log('NO EYE BUTTON FOUND')
  }
})
