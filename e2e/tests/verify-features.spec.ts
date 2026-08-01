import { test } from '@playwright/test'
import * as fs from 'fs'

test('验证金租+发票+详情新功能', async ({ page }) => {
  const log: string[] = []
  await page.goto('http://localhost:8080/login', { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入账号"]', 'cfo')
  await page.fill('input[placeholder="请输入密码"]', 'sie123')
  await page.click('button:has-text("登")')
  await page.waitForTimeout(1500)

  // 1. 金租流程页
  await page.goto('http://localhost:8080/leasing', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1000)
  const leasingRows = await page.locator('table tbody tr').count()
  const leasingText = await page.locator('body').innerText().catch(() => '')
  log.push(`金租流程: ${leasingRows}行, 有"放款"字样=${leasingText.includes('放款')}, 有"金租"=${leasingText.includes('金租')}`)
  await page.screenshot({ path: 'screenshots/verify-leasing.png' })

  // 2. 金租详情（点"详情"）
  const detailBtn = page.locator('button:has-text("详情")').first()
  if (await detailBtn.count()) {
    await detailBtn.click()
    await page.waitForTimeout(800)
    const drawerText = await page.locator('.n-drawer-content').innerText().catch(() => '')
    log.push(`金租详情: 有时间线=${drawerText.includes('节点') || drawerText.includes('接触')}, 有还款=${drawerText.includes('还款')}`)
    await page.screenshot({ path: 'screenshots/verify-leasing-detail.png' })
  }

  // 3. 发票页（OCR 按钮）
  await page.goto('http://localhost:8080/invoices', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  const invText = await page.locator('body').innerText().catch(() => '')
  log.push(`发票: 有OCR=${invText.includes('OCR')}, 有对账=${invText.includes('对账')}`)
  // 点"新增发票"看 OCR 按钮
  const createBtn = page.locator('button:has-text("新增发票")').first()
  if (await createBtn.count()) {
    await createBtn.click()
    await page.waitForTimeout(500)
    const modalText = await page.locator('.n-modal').innerText().catch(() => '')
    log.push(`发票创建弹窗: 有OCR上传=${modalText.includes('OCR')}`)
    await page.screenshot({ path: 'screenshots/verify-invoice-ocr.png' })
  }

  // 4. 合同详情 + 上传
  await page.goto('http://localhost:8080/master/contracts', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  const eyeBtn = page.locator('button[title="详情"]').first()
  if (await eyeBtn.count()) {
    await eyeBtn.click()
    await page.waitForTimeout(500)
    const contractDetail = await page.locator('.n-drawer-content').innerText().catch(() => '')
    log.push(`合同详情: 有附件=${contractDetail.includes('附件')}, 有上传=${contractDetail.includes('上传')}`)
    await page.screenshot({ path: 'screenshots/verify-contract-upload.png' })
  }

  fs.writeFileSync('verify-features.txt', log.join('\n'), 'utf-8')
})
