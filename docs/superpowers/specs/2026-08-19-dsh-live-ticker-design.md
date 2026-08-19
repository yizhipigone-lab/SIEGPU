# dsh-live-ticker 设计文档

- 日期：2026-08-19
- 状态：草案（待用户 review）
- 目标 profile：`web`（`C:\Users\liuziheng\.dsh\profiles\web`）
- 对应会话决策：输入框下方（`conversation.composer.dock`）；新闻源 = 东方财富新闻列表；本轮范围 = 先出设计文档

## 1. 背景与目标

在 DSH Web 对话框**底部（输入框卡片下方）**添加两个可折叠行（默认展开）：

1. **行情行**：实时显示上证指数、创业板指、科创50、中证A500 的现价与涨跌幅。
2. **新闻行**：滚动显示最新财经新闻（标题 + 时间 + 原文链接）。

设计目标：

- 纯展示，不进入对话流、不产生 token 消耗、不影响模型上下文。
- 可折叠（默认打开），可手动刷新，标签页隐藏时自动暂停轮询。
- 数据源稳定可用（已全部实测）。

## 2. 数据源（已实测 2026-08-19）

### 2.1 行情：东方财富 push2（主源）+ 腾讯 qt.gtimg.cn（备源）

东方财富批量接口（一次请求拿 4 个指数，CORS `*`，浏览器可直连）：

```
GET https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=1.000001,0.399006,1.000688,1.000510&fields=f2,f3,f12,f14
```

| 指数 | secid | 实测值（示例） |
|---|---|---|
| 上证指数 | `1.000001` | 3990.30 / +0.19% |
| 创业板指 | `0.399006` | 3705.56 / -0.93% |
| 科创50 | `1.000688` | 1790.87 / +0.11% |
| 中证A500 | `1.000510` | 5892.61 / -0.32% |

字段：`f12`=代码，`f14`=名称，`f2`=现价，`f3`=涨跌幅。

> ⚠️ 注意：`0.000510` 是深市个股"新金路"，**中证A500 必须是 `1.000510`**（已实测确认）。

腾讯备源（CORS `*`，格式为 `~` 分隔文本）：

```
GET https://qt.gtimg.cn/q=sh000001,sz399006,sh000688,sh000510
```

字段：`[1]`=名称，`[3]`=现价，`[32]`=涨跌幅。腾讯对中证A500 的代码需在实现时再核对（`sh000510`），主源东财优先，腾讯仅作降级。

### 2.2 新闻：东方财富新闻列表（host 侧代理）

```
GET https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_news_col&column=350&order=1&needInteractData=0&page_index=1&page_size=10&req_trace=1&fields=code,showTime,title,url
```

- 返回：`data.list[]`，含 `title`、`showTime`、`url`（已实测可用）。
- **无 CORS 头** → 浏览器不能直连，必须由 host 侧（Node）代理抓取后经 DSH Remote 转发给 client。
- 华尔街见闻：RSS 主域名 403、官方 API 字段异常 → 放弃作为主源（可作为后续增强，见 §7）。

## 3. 架构

**方案 A（采用）：单 bundle 插件，host + client 双面。**

```
┌─────────────────────────────────────────────────────┐
│  dsh-live-ticker（bundle）                           │
│                                                     │
│  host 面（Node，cordis.patch.yml 注册）               │
│    └─ live-ticker 服务：代理抓取东财新闻列表            │
│       ├─ Remote: live-ticker/fetch-news  (client 调) │
│       └─ 缓存 30s，失败返回上次快照 + stale 标记        │
│                                                     │
│  client 面（浏览器，dsh.client 注入）                  │
│    ├─ conversation.composer.dock 注册两个折叠行        │
│    ├─ 行情：浏览器直连东财 push2（CORS *）             │
│    └─ 新闻：调 host Remote 拿新闻快照                  │
└─────────────────────────────────────────────────────┘
```

为什么指数放浏览器直连、新闻放 host 代理：

- 指数接口 CORS `*`，浏览器直连最简单，**零后端**，5s 轮询无压力。
- 新闻接口无 CORS，但 host 抓取正是 DSH 标准能力（dsh-news-plugin 同款思路），client 通过 Remote 调用，实现同样简单。

## 4. 组件与槽位

### 4.1 挂载点：`conversation.composer.dock`

- 类型：`list` / `scope: session` / owner 共享 `InputZone`（`{ session, input }` 快照）。
- 位置：输入框卡片**下方**的带（官方 stats 行所在）。
- 两个折叠行以**一个**注册条目渲染（一个组件内部画两个 `<details>`），避免两个条目之间的纵向间隔不一致。
- 注册条目 render 条件：`session` 存在时渲染（hero 空态不显示）。

### 4.2 插件结构（参照 dsh-i18n / dshmarket 的 client 形态）

```
dsh-live-ticker/
├── package.json            # name/version/main/exports，dsh.bundle.patch + dsh.client.inject
├── cordis.patch.yml        # insert: - id: live-ticker (host 行)；client 注入
├── src/
│   ├── index.ts            # host：apply(ctx) → 注册 live-ticker 服务 + Remote
│   ├── news.ts             # host：fetchEfinanceNews() 抓取 + 缓存
│   └── client/
│       ├── index.tsx       # client 入口：注册 composer.dock 条目
│       ├── TickerBar.tsx   # 两个可折叠行组件（指数行 + 新闻行）
│       └── api.ts          # 浏览器端：直连东财 push2 + 调 host Remote
└── README.md
```

client 入口按 DSH 规范导出（`window.__ModuleLoader__` 产物由构建产出；开发期参照 dsh-i18n 的 `lib/client.js` 形态 + `dsh.client.inject` 声明 `@deepseek-ai/dsh-client-connection`（Remote）与 `@deepseek-ai/dsh-client-ui-slots`（slots））。

## 5. UI 细节

```
┌──────────────────────────────────────────────────────────┐
│ ▸ 行情 上证 3990.30 +0.19% │ 创业板 3705.56 -0.93% │ …    │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ 上证指数  3990.30 ▲+0.19%   创业板指  3705.56 ▼-0.93% │ │
│ │ 科创50    1790.87 ▲+0.11%   中证A500  5892.61 ▼-0.32% │ │
│ └──────────────────────────────────────────────────────┘ │
│ ▸ 财经快讯（滚动）  …最新的 5 条横向滚动…                  │
└──────────────────────────────────────────────────────────┘
```

- **折叠**：两个 `<details open>`（`summary` 行：标题 + 手动刷新按钮 + 最后更新时间）。
- **指数行**：2×2 网格或 4 连排（视 `composer.dock` 宽度自适应；窄屏换行）。
  - 每个指数：名称 + 现价 + 涨跌幅徽标；**涨红跌绿**（A股惯例），持平灰色。
  - 刷新间隔 5s；请求失败保留上次值并显示"·"（stale 标记），连续 3 次失败显示"连接失败"。
- **新闻行**：横向滚动 ticker，最新在前；悬停暂停滚动；点击标题在新标签打开原文；`<title>` 悬浮显示完整标题；显示发布时间（`showTime` 截断到分钟）。
  - 刷新间隔 60s（走 host 缓存，实际东财每 30s 拉一次）。
- **生命周期**：`document.visibilitychange` 隐藏时暂停所有轮询与滚动动画，恢复时立即刷新一次。
- **主题**：全部使用 CSS 变量（`var(--dsw-alias-*)` 同 dsh-i18n 用法），自动适配暗色/亮色；不写死颜色。
- **宽度约束**：`composer.dock` 在输入框列宽内，组件最大宽度跟随宿主，不自设宽度。

## 6. 数据流与错误处理

### 6.1 指数（浏览器直连）

```
TickerBar useEffect
  → fetchEfinanceQuotes(secids)         // 东财 push2
  → 成功: setQuotes / 失败: stale 标记
  → setTimeout 5s（visibility 可见时）
```

### 6.2 新闻（host 代理）

```
TickerBar useEffect
  → ctx.connection.call('live-ticker/fetch-news')   // Remote → host
  → host: 缓存命中(<30s) ? 返回缓存 : 抓东财 → 更新缓存
  → 返回 { items, fetchedAt, stale }
  → 失败: 显示上次快照 + "更新失败" 小字
```

Remote 签名：

```ts
// host 注册
ctx.remote.define('live-ticker/fetch-news', async () => {
  const cached = cache.get('news')
  if (cached && Date.now() - cached.fetchedAt < 30_000) return cached
  try {
    const items = await fetchEfinanceNews()
    const snapshot = { items, fetchedAt: Date.now(), stale: false }
    cache.set('news', snapshot)
    return snapshot
  } catch (e) {
    return cache.get('news') ?? { items: [], fetchedAt: 0, stale: true, error: String(e) }
  }
})
```

若 DSH Remote 机制与现有插件（dsh-news-plugin 是纯 host 工具而非 Remote）不一致，降级方案：host 注册一个 `live-ticker-fetch-news` 工具供 client 经 `connection` 调用，或在 client 侧用 `fetch` 走 DSH 网关代理路径——实现时以现有插件实际写法为准（dshmarket/dsh-i18n 的 connection 用法为参考）。

## 7. 不做的事（YAGNI）

- ❌ 不接入华尔街见闻（不可靠）。
- ❌ 不做自选股/板块/个股搜索（后续可加，接口同源）。
- ❌ 不把行情/新闻写入对话流或会话存储（纯展示，无持久化）。
- ❌ 不做设置面板（折叠状态用 `localStorage` 记忆即可；如需开关再升级到 Settings）。

## 8. 测试

- host 侧：`fetchEfinanceNews()` 用 node 直接跑通（返回 ≥1 条、字段齐全）；缓存命中/未命中两条路径。
- client 侧：真实启动 `dsh --profile web` 后人工验收：
  - 两个折叠行默认展开，出现在输入框下方；
  - 4 个指数数值与东财网页一致，涨跌颜色正确；
  - 新闻行滚动、悬停暂停、点击开链接；
  - 隐藏标签页 10s 再回来：指数立即刷新，无堆积轮询；
  - 断网时显示 stale/失败态，恢复后自愈。
- 兼容性：确认与 dsh-i18n、dshmarket、dsh-genui 等已装 client 插件无槽位冲突（composer.dock 是 list 槽，多条目可共存）。

## 9. 安装与交付

- 源码目录：`E:\1target\SIEGPU\dsh-live-ticker\`（独立于 SIEGPU 业务代码，后续可单独 git 仓库）。
- 安装：`dsh plugin --profile web add "file:E:/1target/SIEGPU/dsh-live-ticker"`（参照现有 dsh-i18n 的 file: 安装方式），或先以 `~/.dsh/plugins/dsh-live-ticker` 本地目录形态挂载验证。
- 重启 `dsh --profile web` 生效。
- 卸载：`dsh plugin --profile web remove dsh-live-ticker`。

## 10. 风险与开放问题

1. `conversation.composer.dock` 为 list 槽：多个插件同时注册时按 order 排列，需确认当前 web profile 无其他插件占用该槽（若占用，行为仍是共存，仅顺序问题）。
2. host Remote 的准确 API 形态需在实现第一步对着 `dsh-news-plugin` / `dshmarket` 的实际 client 代码核实（§6.2 已给降级方案）。
3. 腾讯 `sh000510`（中证A500）代码待实现时核对；备源仅在主源连续失败时启用。
4. 中证A500 为 2024 年新指数，东财返回正常（已实测），若个别行情软件不一致以本设计 secid 为准。
