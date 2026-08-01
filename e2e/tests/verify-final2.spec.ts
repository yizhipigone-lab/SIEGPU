import { test } from '@playwright/test'
import * as fs from 'fs'

const log: string[] = []

test('最终验证', async ({ page }) => {
  try {
    await page.goto('http://localhost:8080/login', { waitUntil: 'networkidle' })
    await page.fill('input[placeholder="请输入账号"]', 'cfo')
    await page.fill('input[placeholder="请输入密码"]', 'sie123')
    await page.click('button:has-text("登")')
    await page.waitForTimeout(2000)
  } catch (e: any) { log.push(`LOGIN FAIL: ${e.message}`); fs.writeFileSync('verify-final.txt', log.join('\n')); return }

  // 项目详情 → 关联子表
  try {
    await page.goto('http://localhost:8080/master/projects', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1000)
    const eyeBtn = page.locator('button[title="详情"]').first()
    if (await eyeBtn.count()) {
      await eyeBtn.click()
      await page.waitForTimeout(2000)
      const detail = await page.locator('.n-drawer-content').innerText().catch(() => '')
      log.push(`项目详情: 合同Tab=${detail.includes('合同')} 订单Tab=${detail.includes('订单')} 金租Tab=${detail.includes('金租')} 资产Tab=${detail.includes('资产')}`)
      const nums = detail.match(/(\d+)\)/g)
      log.push(`  关联数据: ${nums ? nums.join(' ') : '无'}`)
      await page.screenshot({ path: 'screenshots/verify-project-tabs.png' })
    } else { log.push('项目: 无详情按钮') }
    await page.keyboard.press('Escape')
    await page.waitForTimeout(500)
  } catch (e: any) { log.push(`项目详情 FAIL: ${e.message?.slice(0,80)}`) }

  // 搜索
  try {
    const searchInput = page.locator('input[placeholder="搜索..."]').first()
    if (await searchInput.count()) {
      await searchInput.fill('5090')
      await page.waitForTimeout(300)
      const filtered = await page.locator('table tbody tr').count()
      log.push(`搜索"5090": ${filtered}行`)
      await searchInput.fill('')
      await page.waitForTimeout(200)
      const all = await page.locator('table tbody tr').count()
      log.push(`清空后: ${all}行`)
    } else { log.push('无搜索框') }
  } catch (e: any) { log.push(`搜索 FAIL: ${e.message?.slice(0,80)}`) }

  fs.writeFileSync('verify-final.txt', log.join('\n'), 'utf-8')
})
