import { test, expect, Locator, Page } from '@playwright/test'

// 设备清单页：打开 → 新增设备 → 状态筛选 → 批次组合
// 四个用例共享数据库状态（新增的设备供后续用例使用），故串行执行。

async function login(page: Page) {
  await page.goto('/login')
  await page.getByPlaceholder('请输入账号').fill('cfo')
  await page.getByPlaceholder('请输入密码').fill('sie123')
  await page.getByRole('button', { name: /登.*录/ }).click()
  await expect(page).toHaveURL(/\/$/)
}

// 等待「可见的下拉菜单」数量达到目标：naive-ui 的 .n-base-select-menu 打开时可见、关闭后隐藏。
// 用它显式同步下拉的开/关，避免连续操作两个下拉时「第二个没真正打开」的竞态。
async function waitForMenu(page: Page, wantOpen: boolean, iterations = 40): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    const n = await page.locator('.n-base-select-menu').filter({ visible: true }).count()
    if (wantOpen ? n > 0 : n === 0) return
    await page.waitForTimeout(100)
  }
}

// naive-ui 的 n-select 有三个坑，本助手收敛成「开下拉 → 选第一个可见 option」的原子动作：
//   ① placeholder 不渲染到 <input>（filterable select 连 .n-base-selection-placeholder 都不暴露），
//      只能按所属 n-form-item 的 label 文本定位 .n-base-selection；
//   ② 关闭下拉不清除 option DOM，残留隐藏项，全局 .first() 会抓到旧下拉的隐藏 option → 必须过滤可见；
//   ③ 下拉开/关有 ~200ms 过渡动画，过渡期内 option "not stable"，连续开两个下拉时第二个可能没真正打开。
function selectByLabel(scope: Page | Locator, label: string): Locator {
  return scope.locator('.n-form-item', { hasText: label }).locator('.n-base-selection')
}

async function selectFirstOption(scope: Locator, label: string, page: Page): Promise<void> {
  await selectByLabel(scope, label).click()
  await waitForMenu(page, true)            // 确认下拉确实打开
  await page.waitForTimeout(280)           // 等过渡动画收尾，避免 option not stable
  const opt = page.locator('.n-base-select-option').filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await waitForMenu(page, false)           // 等下拉关闭，确保下一次打开干净
}

// 按文本选 option（节点推进需指定具体节点/状态，不能盲选第一个）。同样遵守三坑时序。
async function selectOptionByText(scope: Locator, label: string, text: string, page: Page): Promise<void> {
  await selectByLabel(scope, label).click()
  await waitForMenu(page, true)
  await page.waitForTimeout(280)
  const opt = page.locator('.n-base-select-option', { hasText: text }).filter({ visible: true }).first()
  await opt.waitFor({ state: 'visible' })
  await opt.click()
  await waitForMenu(page, false)
}

// 点 modal 内某按钮后，等一条「新的」含 text 的 n-message 出现。
// 用 count 增量而非 .last()：naive-ui message 退出有过渡，旧 .n-message 残留 DOM，
// 既会触发 strict-mode 多元素误报，也会让紧凑循环里 .last() 命中上一轮的旧消息（假阳性）。
// count 必须比点击前增加，才能证明本轮真的弹了新消息。
async function clickAndExpectMessage(modal: Locator, buttonName: string, page: Page, text: string): Promise<void> {
  const before = await page.locator('.n-message', { hasText: text }).count()
  await modal.getByRole('button', { name: buttonName }).click()
  await expect.poll(
    async () => page.locator('.n-message', { hasText: text }).count(),
    { timeout: 5000 },
  ).toBeGreaterThan(before)
}

// 通过 UI 新增一台设备（自动 SN）；新建设备 created_at 最新 → 出现在表格首行。
// 关键：msg.success 在 load() 之前触发，故不能见消息就返回——必须等到首行内容真正变更，
// 否则后续点「推进」可能落在刷新前的旧行上（竞态）。
async function createDeviceViaUI(page: Page): Promise<void> {
  const beforeFirst = await page.locator('.device-list-table tbody tr').first().textContent().catch(() => null)
  await page.getByRole('button', { name: '新增设备' }).click()
  const modal = page.locator('.n-modal')
  await modal.waitFor()
  await selectFirstOption(modal, '项目', page)
  await selectFirstOption(modal, '设备型号', page)
  await clickAndExpectMessage(modal, '创建', page, '设备已创建')
  // 等表格刷新：首行内容变化即证明新设备已排到首行
  await expect(async () => {
    const now = await page.locator('.device-list-table tbody tr').first().textContent()
    expect(now).not.toBeNull()
    expect(now).not.toEqual(beforeFirst)
  }).toPass({ timeout: 5000 })
}

// 行内「推进」按钮：把首行设备的指定节点推进到指定状态（单次 stage+status 提交）。
async function advanceViaRow(page: Page, stage: string, status: string): Promise<void> {
  await page.locator('.device-list-table tbody tr').first().getByRole('button', { name: '推进' }).click()
  const modal = page.locator('.n-modal')
  await modal.waitFor()
  await selectOptionByText(modal, '节点', stage, page)
  await selectOptionByText(modal, '状态', status, page)
  await clickAndExpectMessage(modal, '确认推进', page, '节点推进完成')
}

test.describe.serial('设备清单', () => {
  test('打开设备清单页', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    await expect(page.getByRole('heading', { name: '设备清单' })).toBeVisible()
    await expect(page.getByRole('button', { name: '新增设备' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Excel 导入' })).toBeVisible()
    await expect(page.locator('.device-list-table')).toBeVisible()
  })

  test('新增设备（SN 自动生成）', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    await page.getByRole('button', { name: '新增设备' }).click()
    const modal = page.locator('.n-modal')
    await modal.waitFor()

    await selectFirstOption(modal, '项目', page)
    await selectFirstOption(modal, '设备型号', page)

    await modal.getByRole('button', { name: '创建' }).click()
    await expect(page.locator('.n-message')).toContainText('设备已创建')
    // SN 规则 GPU-{yyyymm}-{seq5}
    await expect(page.locator('.device-list-table tbody')).toContainText('GPU-')
  })

  test('按状态筛选（订货）', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    // 筛选栏状态下拉（非 filterable，有 .n-base-selection-placeholder）
    await page.locator('.n-select', { has: page.locator('.n-base-selection-placeholder', { hasText: '状态' }) }).click()
    await waitForMenu(page, true)
    await page.waitForTimeout(280)
    await page.locator('.n-base-select-option', { hasText: '订货' }).filter({ visible: true }).first().click()
    // 表格只出现「订货」状态的行（上一步新增的设备默认即为订货）
    await expect(page.locator('.device-list-table tbody')).toContainText('GPU-')
    await expect(page.locator('.device-list-table tbody')).toContainText('订货')
    await expect(page.locator('.device-list-table tbody')).not.toContainText('点亮验收')
  })

  test('批次组合：选中设备挂入批次订单', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    // 勾选第一行
    await page.locator('.device-list-table tbody .n-checkbox').first().click()
    await page.getByRole('button', { name: /批次组合/ }).click()

    const modal = page.locator('.n-modal')
    await modal.waitFor()
    await selectFirstOption(modal, '批次订单', page)
    await modal.getByRole('button', { name: '确认组合' }).click()
    await expect(page.locator('.n-message')).toContainText('批次组合完成')
  })

  test('批量推进：选中设备推进到在途', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    await createDeviceViaUI(page)
    // 订货：未开始 → 进行中 → 已完成，两轮后状态列由「订货」物化为「在途」。
    // submitAdvance 每轮清空勾选并 load()，故每轮需重新勾选首行。
    for (const status of ['进行中', '已完成']) {
      await page.locator('.device-list-table tbody .n-checkbox').first().click()
      await page.getByRole('button', { name: /批量推进/ }).click()
      const modal = page.locator('.n-modal')
      await modal.waitFor()
      await selectOptionByText(modal, '节点', '订货', page)
      await selectOptionByText(modal, '状态', status, page)
      await clickAndExpectMessage(modal, '确认推进', page, '节点推进完成')
    }
    // 状态列刷新：首行物化状态 = 在途（订货已完成，下一未完成节点为在途）
    await expect(page.locator('.device-list-table tbody tr').first()).toContainText('在途')
  })

  test('单台推进：全链路推进到点亮验收', async ({ page }) => {
    // 14 轮串行模态交互（7 节点 × 进行中+已完成），每轮含 2 次下拉 + toast 轮询 + naive-ui 过渡，
    // 本就是长测试（~110s）；叠加共享 dev 库 e2e 历次累积的列表膨胀（devices 行多 → 表格渲染慢）会越
    // 90s 默认超时。test.slow() 3 倍预算是对「合法长测试」的诚实声明，非掩盖逻辑错（测试恒通过）。
    test.slow()
    await login(page)
    await page.goto('/devices')
    await createDeviceViaUI(page)
    // 7 节点逐个 进行中→已完成，验证完整状态机 + 点亮验收终态（计费起点信号）
    const stages = ['订货', '在途', '到货', '己方压测', '上架', '客户压测', '点亮验收']
    for (const stage of stages) {
      await advanceViaRow(page, stage, '进行中')
      await advanceViaRow(page, stage, '已完成')
    }
    // 全部 7 节点已完成 → 状态物化为「点亮验收」
    await expect(page.locator('.device-list-table tbody tr').first()).toContainText('点亮验收')
  })
})
