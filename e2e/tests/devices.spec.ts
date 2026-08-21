import { test, expect, Locator, Page } from '@playwright/test'

// 设备清单页：打开 → 新增设备 → 状态筛选 → 批次组合 → 批量推进 → 单台全链路推进
//
// 债③ flake 根治（2026-08-10）：
// 旧版用 test.describe.serial + 「首行 = 刚建设备」假设（.device-list-table tbody tr .first()）。
// 共享 dev 库全套并发时，多个 worker 同时建设备，首行可能是别 worker 刚建的设备 → 操作/断言落错设备
// → ~50% flake；serial 又把单 test 失败级联成后续「did not run」。
// 修法三件套：① 去 serial（消级联：一个失败不再跳后续）；② createDeviceViaUI 用 waitForResponse
// 抓 POST /api/devices 响应里的 sn（确定性锚点，唯一绑定「我点的这次创建」）；③ 所有「定位刚建设备」
// 的操作改按 sn 行定位（rowBySn），彻底消除首行假设。6 个 test 各自造数、自包含、无数据依赖。
// 造数可清理：UI 自动生成 sn 形如 GPU-{yyyymm}-{seq}，globalTeardown（cleanup_e2e.py）按 ^GPU- 清。

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
// 超时 5s→15s：全套连跑时共享 dev 库行数累积、表格渲染变慢，toast 出现晚于 5s 属于负载问题
// 而非业务错（单跑恒过、快照里状态列已物化「在途」）；拉长等待是消抖，不断言逻辑。
async function clickAndExpectMessage(modal: Locator, buttonName: string, page: Page, text: string): Promise<void> {
  const before = await page.locator('.n-message', { hasText: text }).count()
  await modal.getByRole('button', { name: buttonName }).click()
  await expect.poll(
    async () => page.locator('.n-message', { hasText: text }).count(),
    { timeout: 15000 },
  ).toBeGreaterThan(before)
}

// 按唯一 SN 定位设备行（债③锚点）：sn 全局唯一，filter hasText 不会误中别行。
// 替代旧的 .first()——全套并发时首行可能是别 worker 刚建的设备，唯有 sn 能唯一定位「我的设备」。
function rowBySn(page: Page, sn: string): Locator {
  return page.locator('.device-list-table tbody tr').filter({ hasText: sn })
}

// 通过 UI 新增一台设备（自动 SN），返回该设备 SN。
// 关键：用 waitForResponse 拦截 POST /api/devices 响应拿 sn（确定性），替代旧的「等首行 textContent 变化」
// （旧法假设新设备排首行，全套并发下不成立）。谓词 endsWith('/api/devices') 精确排除子路径
// （/batch-assign、/{id}/stage 等），且只认 POST。waitForResponse 在点「新增设备」前注册，中间选项目/
// 型号不发 POST /devices，故只会命中「创建」按钮触发的本次请求。
async function createDeviceViaUI(page: Page): Promise<string> {
  const respPromise = page.waitForResponse(
    (r) => r.url().endsWith('/api/devices') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '新增设备' }).click()
  const modal = page.locator('.n-modal')
  await modal.waitFor()
  await selectFirstOption(modal, '项目', page)
  await selectFirstOption(modal, '设备型号', page)
  await modal.getByRole('button', { name: '创建' }).click()
  const resp = await respPromise
  const { sn } = await resp.json()
  expect(sn, '新建设备应返回 GPU- 开头的 SN').toMatch(/^GPU-/)
  // 等表格刷新：本 SN 行可见即证明已渲染（sn 唯一锚点，不依赖排序/首行）
  await expect(rowBySn(page, sn)).toBeVisible({ timeout: 5000 })
  return sn
}

// 行内「推进」按钮：把 sn 所在行的设备推进指定节点到指定状态（单次 stage+status 提交）。
async function advanceViaRow(page: Page, sn: string, stage: string, status: string): Promise<void> {
  await rowBySn(page, sn).getByRole('button', { name: '推进' }).click()
  const modal = page.locator('.n-modal')
  await modal.waitFor()
  await selectOptionByText(modal, '节点', stage, page)
  await selectOptionByText(modal, '状态', status, page)
  await clickAndExpectMessage(modal, '确认推进', page, '节点推进完成')
}

test.describe('设备清单', () => {
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
    // createDeviceViaUI 内部已断言返回 sn 匹配 GPU- 并等行可见
    const sn = await createDeviceViaUI(page)
    expect(sn).toMatch(/^GPU-/)
  })

  test('按状态筛选（订货）', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    // 自建一台（默认状态=订货）→ 拿 sn 锚点
    const sn = await createDeviceViaUI(page)
    // 筛选栏状态下拉：不在 n-form-item 里、无 label，用 placeholder 文本「状态」反查所属 .n-select。
    // 注意 hasText 只吃 string/regex，要传 Locator 必须用 filter({ has: ... })——否则 Locator 被 toString
    // 成字面量字符串当 hasText 匹配，永不命中 → 90s 超时（本 test 第一版踩过）。
    await page.locator('.n-select').filter({ has: page.locator('.n-base-selection-placeholder', { hasText: '状态' }) }).click()
    await waitForMenu(page, true)
    await page.waitForTimeout(280)
    await page.locator('.n-base-select-option', { hasText: '订货' }).filter({ visible: true }).first().click()
    // 筛选生效：我建的设备（订货）应可见，且结果中不含「点亮验收」
    await expect(rowBySn(page, sn)).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.device-list-table tbody')).not.toContainText('点亮验收')
  })

  test('批次组合：选中设备挂入批次订单', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    const sn = await createDeviceViaUI(page)
    // 勾选本设备行（按 sn 定位，不靠首行）
    await rowBySn(page, sn).locator('.n-checkbox').first().click()
    // W4 起页面有「批次组合」+「销售批次组合」两个按钮 → 开头锚定防 strict 双命中
    await page.getByRole('button', { name: /^批次组合/ }).click()

    const modal = page.locator('.n-modal')
    await modal.waitFor()
    await selectFirstOption(modal, '批次订单', page)
    // 用 clickAndExpectMessage（按文本过滤 + count 增量），而非裸 .n-message：createDeviceViaUI
    // 弹的「设备已创建」此时仍残留 DOM（naive-ui 退出过渡），裸 .n-message 会命中 2 条触发 strict 报错。
    await clickAndExpectMessage(modal, '确认组合', page, '批次组合完成')
  })

  test('批量推进：选中设备推进到在途', async ({ page }) => {
    await login(page)
    await page.goto('/devices')
    const sn = await createDeviceViaUI(page)
    // 订货：未开始 → 进行中 → 已完成，两轮后状态列由「订货」物化为「在途」。
    // submitAdvance 每轮清空勾选并 load()，故每轮需重新勾选本设备行（按 sn）。
    for (const status of ['进行中', '已完成']) {
      await rowBySn(page, sn).locator('.n-checkbox').first().click()
      await page.getByRole('button', { name: /批量推进/ }).click()
      const modal = page.locator('.n-modal')
      await modal.waitFor()
      await selectOptionByText(modal, '节点', '订货', page)
      await selectOptionByText(modal, '状态', status, page)
      // 成功即关抽屉并 reload（确定性信号）；替代 toast 计数——message 退出过渡 + 16 worker
      // 并发负载下 toast 晚到/错过会导致 15s 超时 flake（债③头注释已述）。最终状态由下方「在途」断言兜底。
      await modal.getByRole('button', { name: '确认推进' }).click()
      await expect(modal).toBeHidden({ timeout: 15000 })
    }
    // 本设备状态列物化 = 在途（订货已完成，下一未完成节点为在途）
    await expect(rowBySn(page, sn)).toContainText('在途')
  })

  test('单台推进：全链路推进到点亮验收', async ({ page }) => {
    // 14 轮串行模态交互（7 节点 × 进行中+已完成），每轮含 2 次下拉 + toast 轮询 + naive-ui 过渡，
    // 本就是长测试（~110s）；叠加共享 dev 库 e2e 历次累积的列表膨胀（devices 行多 → 表格渲染慢）会越
    // 90s 默认超时。test.slow() 3 倍预算是对「合法长测试」的诚实声明，非掩盖逻辑错（测试恒通过）。
    test.slow()
    await login(page)
    await page.goto('/devices')
    const sn = await createDeviceViaUI(page)
    // 7 节点逐个 进行中→已完成，验证完整状态机 + 点亮验收终态（计费起点信号）
    const stages = ['订货', '在途', '到货', '己方压测', '上架', '客户压测', '点亮验收']
    for (const stage of stages) {
      await advanceViaRow(page, sn, stage, '进行中')
      await advanceViaRow(page, sn, stage, '已完成')
    }
    // 全部 7 节点已完成 → 本设备状态物化为「点亮验收」
    await expect(rowBySn(page, sn)).toContainText('点亮验收')
  })
})
