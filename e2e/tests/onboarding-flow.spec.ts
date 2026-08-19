import { test, expect, type Page } from '@playwright/test'

// 新手引导专项（P0 泳道化流程图 + P2 页面级定位提示）—— 端到端铁律：
//   a. 首页流程图三泳道渲染（角色泳道 + 单据/动作节点 + 本角色泳道「你负责」标签）
//   b. 业务页页头一句话定位（流程第几步 · 谁负责 · 依赖上一步）
// 不造数：纯结构断言，与共享 dev-DB 数据状态无关。

async function uiLogin(page: Page, username: string) {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill(username)
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/, { timeout: 8000 })
}

test('a. 采购账号：首页流程图三泳道 + 本角色泳道高亮', async ({ page }) => {
  await uiLogin(page, 'buyer')
  const flow = page.getByTestId('flow-map')
  await expect(flow).toBeVisible()

  // 三条泳道（角色名标题）
  await expect(flow.getByText('采购对接人')).toBeVisible()
  await expect(flow.getByText('项目交付负责人')).toBeVisible()
  await expect(flow.getByText('财务专员')).toBeVisible()
  // 单据节点（doc）与动作节点（action）都在
  await expect(flow.getByText('项目建立')).toBeVisible()
  await expect(flow.getByText('点亮验收')).toBeVisible()
  // 本角色泳道打「你负责」标签（用 .lane-mine 类名定位，避开卡片头的「高亮的是你负责的环节」）
  await expect(flow.locator('.lane-mine')).toBeVisible()
  await expect(flow.locator('.lane-mine')).toHaveText('你负责')
})

test('b. 采购账号：合同页页头定位提示', async ({ page }) => {
  await uiLogin(page, 'buyer')
  await page.goto('/master/contracts')
  const hint = page.locator('.page-hint')
  await expect(hint).toBeVisible()
  await expect(hint).toContainText('流程第')
  await expect(hint).toContainText('采购对接人')
})

test('c. 财务账号：金租页页头定位提示', async ({ page }) => {
  await uiLogin(page, 'finance')
  await page.goto('/leasing')
  await expect(page.locator('.page-hint')).toContainText('金租放款')
})

test('d. 首次登录分步引导 tour：显示并可跳过', async ({ page }) => {
  await uiLogin(page, 'buyer')
  const tour = page.getByTestId('onboarding-tour')
  await expect(tour).toBeVisible({ timeout: 5000 })
  await tour.getByRole('button', { name: '跳过' }).click()
  await expect(tour).toHaveCount(0)
})

test('e. 命令面板「最近访问」：访问过的页面出现在快捷区', async ({ page }) => {
  await uiLogin(page, 'buyer')
  await page.goto('/devices')
  await page.goto('/')
  await page.keyboard.press('Control+K')
  await expect(page.getByTestId('command-input')).toBeVisible()
  const quick = page.locator('.quick-section')
  await expect(quick).toContainText('最近访问')
  await expect(quick).toContainText('设备清单')
})
