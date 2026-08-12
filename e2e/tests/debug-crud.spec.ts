import { test } from '@playwright/test'
import * as fs from 'fs'

// 调试 GenericCrud 是否渲染数据行；抓控制台错误
test('调试 CRUD 页（合同/订单/资产/供应商）', async ({ page }) => {
  const log: string[] = []
  page.on('console', (m) => m.type() === 'error' && log.push(`[err] ${m.text()}`))
  page.on('pageerror', (e) => log.push(`[pageerror] ${e.message}`))

  await page.goto('http://localhost:8088/login', { waitUntil: 'networkidle' })
  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await page.waitForURL('/')

  for (const path of ['/master/suppliers', '/master/customers', '/master/contracts', '/master/orders', '/master/assets']) {
    await page.goto('http://localhost:8088' + path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(700)
    const rows = await page.locator('.n-data-table-tbody .n-data-table-tr').count()
    const empty = await page.locator('.n-data-table-empty').count()
    log.push(`${path}  -> rows=${rows}  emptyState=${empty}`)
  }
  log.push(`CONSOLE_ERRORS: ${log.filter((l) => l.startsWith('[err]') || l.startsWith('[pageerror]')).join(' || ') || 'none'}`)
  fs.writeFileSync('debug-crud-out.txt', log.join('\n'), 'utf-8')
})
