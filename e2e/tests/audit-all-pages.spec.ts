import { test } from '@playwright/test'
import * as fs from 'fs'

test('全页面审计（截图 + 行数 + 控制台错误）', async ({ page }) => {
  const log: string[] = []
  page.on('console', m => { if (m.type() === 'error') log.push(`[err] ${m.text()}`) })
  page.on('pageerror', e => log.push(`[pageerror] ${e.message}`))

  // 登录
  await page.goto('http://localhost:9000/login', { waitUntil: 'networkidle' })
  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await page.waitForURL('http://localhost:9000/')

  const pages = [
    ['首页', 'http://localhost:9000/'],
    ['资金池', 'http://localhost:9000/capital'],
    ['发票对账', 'http://localhost:9000/invoices'],
    ['供应商', 'http://localhost:9000/master/suppliers'],
    ['客户', 'http://localhost:9000/master/customers'],
    ['设备型号', 'http://localhost:9000/master/equipment'],
    ['银行', 'http://localhost:9000/master/banks'],
    ['项目', 'http://localhost:9000/master/projects'],
    ['合同', 'http://localhost:9000/master/contracts'],
    ['订单', 'http://localhost:9000/master/orders'],
    ['资产', 'http://localhost:9000/master/assets'],
  ]

  for (const [name, url] of pages) {
    await page.goto(url, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1000)
    const rows = await page.locator('.n-data-table-tbody .n-data-table-tr').count()
    const empty = await page.locator('.n-data-table-empty').count()
    const cards = await page.locator('.n-card').count()
    const breadcrumb = await page.locator('.n-breadcrumb').innerText().catch(() => '?')
    const title = await page.locator('h3').first().innerText().catch(() => '?')
    log.push(`[${name}] rows=${rows} empty=${empty} cards=${cards} title="${title}" breadcrumb="${breadcrumb.replace(/\n/g,'/')}"`)
    // 截图
    await page.screenshot({ path: `screenshots/audit-${name}.png`, fullPage: true })
  }

  const errors = log.filter(l => l.startsWith('[err]') || l.startsWith('[pageerror]'))
  log.push(`\nERRORS: ${errors.length ? errors.join(' | ') : 'none'}`)
  fs.writeFileSync('audit-all-pages.txt', log.join('\n'), 'utf-8')
})
