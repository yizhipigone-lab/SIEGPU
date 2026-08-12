import { test } from '@playwright/test'
import * as fs from 'fs'

// 调试浏览器登录：抓登录响应状态/Body、控制台错误、最终 URL，写文件便于排查
test('调试登录 cfo/sie123', async ({ page }) => {
  const log: string[] = []
  page.on('console', (m) => m.type() === 'error' && log.push(`[console.error] ${m.text()}`))
  page.on('requestfailed', (r) => log.push(`[requestfailed] ${r.url()} ${r.failure()?.errorText}`))
  page.on('response', (r) => {
    if (r.url().includes('/api/')) log.push(`[resp] ${r.request().method()} ${r.url()} → ${r.status()}`)
  })

  await page.goto('http://localhost:8088/login', { waitUntil: 'networkidle' })
  log.push(`login page url=${page.url()}`)

  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('sie123')

  const loginResp = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/auth/login'), { timeout: 8000 }),
    page.getByRole('button', { name: /登.*录/ }).click(),
  ]).catch((e) => [null, e])

  if (loginResp[0]) {
    const r: any = loginResp[0]
    log.push(`LOGIN RESP status=${r.status()} body=${await r.text()}`)
  } else {
    log.push(`NO LOGIN RESPONSE (timeout/err): ${String(loginResp[1])}`)
  }

  await page.waitForTimeout(1500)
  log.push(`url after login = ${page.url()}`)
  const visibleText = await page.locator('body').innerText().catch(() => '?')
  log.push(`body snippet: ${visibleText.slice(0, 200).replace(/\n/g, ' ')}`)

  fs.writeFileSync('debug-login-out.txt', log.join('\n'), 'utf-8')
  await page.screenshot({ path: 'screenshots/debug-login.png', fullPage: true })
})
