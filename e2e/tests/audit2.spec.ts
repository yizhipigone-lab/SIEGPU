import { test } from '@playwright/test'
import * as fs from 'fs'

const results: string[] = []

test('逐页审计', async ({ page }) => {
  const errs: string[] = []
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()) })
  page.on('pageerror', e => errs.push(e.message))

  // 登录
  await page.goto('http://localhost:9000/login').catch(() => {})
  await page.waitForTimeout(1000)
  await page.fill('input[placeholder="请输入账号"]', 'cfo').catch(() => {})
  await page.fill('input[placeholder="请输入密码"]', 'sie123').catch(() => {})
  await page.click('button:has-text("登")').catch(() => {})
  await page.waitForTimeout(2000)

  const pages: [string,string][] = [
    ['首页', '/'], ['资金池', '/capital'], ['发票对账', '/invoices'],
    ['供应商', '/master/suppliers'], ['客户', '/master/customers'],
    ['设备', '/master/equipment'], ['银行', '/master/banks'],
    ['项目', '/master/projects'], ['合同', '/master/contracts'],
    ['订单', '/master/orders'], ['资产', '/master/assets'],
  ]
  for (const [name, path] of pages) {
    try {
      await page.goto('http://localhost:9000' + path, { waitUntil: 'domcontentloaded', timeout: 8000 })
      await page.waitForTimeout(800)
      const rows = await page.locator('table tbody tr').count()
      const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 300).replace(/\n/g, ' ')
      results.push(`✅ ${name}: rows=${rows} | ${bodyText}`)
      await page.screenshot({ path: `screenshots/audit-${name}.png` }).catch(() => {})
    } catch (e: any) {
      results.push(`❌ ${name}: ${e.message?.slice(0, 100)}`)
    }
  }
  results.push(`CONSOLE_ERRORS: ${errs.length ? errs.join(' | ') : 'none'}`)
  fs.writeFileSync('audit2.txt', results.join('\n'), 'utf-8')
})
