import { test } from '@playwright/test'
import * as fs from 'fs'

test('模块来回切换不丢数据', async ({ page }) => {
  const log: string[] = []
  await page.goto('http://localhost:8080/login', { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入账号"]', 'cfo')
  await page.fill('input[placeholder="请输入密码"]', 'sie123')
  await page.click('button:has-text("登")')
  await page.waitForTimeout(1500)

  // 模拟用户：合同→项目→合同→订单→资产→合同（来回切）
  for (const path of ['/master/contracts', '/master/projects', '/master/contracts',
                       '/master/orders', '/master/assets', '/master/contracts',
                       '/master/suppliers', '/master/contracts']) {
    await page.goto('http://localhost:8080' + path, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(500)
    const rows = await page.locator('table tbody tr').count()
    const text = await page.locator('h3').first().innerText().catch(() => '?')
    log.push(`${path} → ${text}: ${rows}行`)
  }
  fs.writeFileSync('nav-switch.txt', log.join('\n'), 'utf-8')
})
