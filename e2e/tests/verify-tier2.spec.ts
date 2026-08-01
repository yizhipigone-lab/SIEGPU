import { test } from '@playwright/test'
import * as fs from 'fs'
const log: string[] = []
test('验证 ④⑤③⑦', async ({ page }) => {
  await page.goto('http://localhost:9000/login', { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入账号"]', 'cfo')
  await page.fill('input[placeholder="请输入密码"]', 'sie123')
  await page.click('button:has-text("登")')
  await page.waitForTimeout(1500)
  // ⑤ 利润页
  await page.goto('http://localhost:9000/profit', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(500)
  const profitText = await page.locator('body').innerText().catch(() => '')
  log.push(`利润页: 有参数=${profitText.includes('采购')} 有计算=${profitText.includes('计算')}`)
  await page.screenshot({ path: 'screenshots/verify-profit.png' })
  // ③ 导入按钮 + ⑦ 导出按钮
  await page.goto('http://localhost:9000/master/suppliers', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(500)
  const supText = await page.locator('body').innerText().catch(() => '')
  log.push(`供应商: 导入=${supText.includes('导入')} 导出=${supText.includes('导出')}`)
  fs.writeFileSync('verify-tier2.txt', log.join('\n'), 'utf-8')
})
