import { test } from '@playwright/test'
import * as fs from 'fs'

test('验证最终功能', async ({ page }) => {
  test.setTimeout(120_000) // 多页面逐个走访 + 截图，默认 30s 不够
  const log: string[] = []
  await page.goto('http://localhost:8088/login', { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入账号"]', 'cfo')
  await page.fill('input[placeholder="请输入密码"]', 'sie123')
  await page.click('button:has-text("登")')
  await page.waitForTimeout(1500)

  // 1. 项目详情 → 关联子表
  await page.goto('http://localhost:8088/master/projects', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  await page.locator('button[title="详情"]').first().click()
  await page.waitForTimeout(1500)
  const projDetail = await page.locator('.n-drawer-content').innerText().catch(() => '')
  const hasContractTab = projDetail.includes('合同')
  const hasAssetTab = projDetail.includes('资产')
  log.push(`项目详情: 合同Tab=${hasContractTab} 资产Tab=${hasAssetTab}`)
  // 检查 tab 数据
  const tabCounts = projDetail.match(/(\d+)\)/g)
  if (tabCounts) log.push(`  tab 数据: ${tabCounts.join(' ')}`)
  await page.screenshot({ path: 'screenshots/verify-project-tabs.png' })
  await page.keyboard.press('Escape') // 关闭详情抽屉（naive-ui 关闭按钮 class 随版本变化，Escape 最稳）
  await page.waitForTimeout(500)

  // 2. 订单详情 → 点亮按钮（demo订单已点亮，按钮不显示——验证showWhen生效）
  await page.goto('http://localhost:8088/master/orders', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  const orderRows = await page.locator('table tbody tr').count()
  await page.locator('button[title="详情"]').first().click()
  await page.waitForTimeout(500)
  const orderDetail = await page.locator('.n-drawer-content').innerText().catch(() => '')
  // demo order 已点亮 → 点亮按钮不显示（showWhen 正确）
  const hasLightOn = orderDetail.includes('点亮')
  log.push(`订单详情: ${orderRows}行, 已点亮=${orderDetail.includes('已点亮')}, 点亮按钮(应false)=${hasLightOn}`)
  await page.screenshot({ path: 'screenshots/verify-order-detail.png' })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // 3. 搜索
  await page.locator('input[placeholder="搜索..."]').fill('1372')
  await page.waitForTimeout(300)
  const searchedRows = await page.locator('table tbody tr').count()
  await page.locator('input[placeholder="搜索..."]').fill('')
  await page.waitForTimeout(300)
  const allRows = await page.locator('table tbody tr').count()
  log.push(`搜索: 搜"1372"=${searchedRows}行 → 清空=${allRows}行`)
  await page.screenshot({ path: 'screenshots/verify-search.png' })

  fs.writeFileSync('verify-final.txt', log.join('\n'), 'utf-8')
})
