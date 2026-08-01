import { test } from '@playwright/test'
import * as fs from 'fs'

test('复现侧栏导航 404', async ({ page }) => {
  const log: string[] = []
  page.on('response', r => {
    if (r.status() === 404) log.push(`[404] ${r.status()} ${r.url()}`)
  })
  page.on('requestfailed', r => log.push(`[fail] ${r.url()} ${r.failure()?.errorText}`))

  await page.goto('http://localhost:8080/login', { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入账号"]', 'cfo')
  await page.fill('input[placeholder="请输入密码"]', 'sie123')
  await page.click('button:has-text("登")')
  await page.waitForTimeout(1500)

  // 模拟用户点击侧栏：首页→合同→项目→合同（来回切）
  for (const path of ['/', '/master/contracts', '/master/projects', '/master/contracts', '/master/orders', '/master/assets', '/master/suppliers']) {
    await page.goto('http://localhost:8080' + path, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(500)
    const rows = await page.locator('table tbody tr').count()
    log.push(`navigated ${path} rows=${rows}`)
  }
  log.push(`404s: ${log.filter(l => l.includes('[404]')).join(' ; ') || 'none'}`)
  log.push(`FAILs: ${log.filter(l => l.includes('[fail]')).join(' ; ') || 'none'}`)
  fs.writeFileSync('repro-404.txt', log.join('\n'), 'utf-8')
})
