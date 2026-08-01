# SIEGPU ERP — 设计系统（单一真相源）

> 2026-07-31 与用户 grilling 共识定稿。所有前端页面以此为据。

## 方向
浅色·专业金融后台（dark sidebar + light content）。人群：3-5 财务/采购，白天办公室桌面浏览器。

## 色板
| 角色 | 值 |
|---|---|
| 背景 `--c-bg` | `#F5F7FA` |
| 表面 `--c-surface` | `#FFFFFF` |
| 文字 `--c-text` | `#0F172A` |
| 次要文字 `--c-text-2` | `#64748B` |
| 边框 `--c-border` | `#E2E8F0` |
| 主色（深金）`--c-primary` | `#B45309`（hover `#92400E`，pressed `#7C2D12`） |
| 主色淡（选中底） | `#FEF3C7` |
| 成功 | `#16A34A` |
| 警告（橙，让开金色） | `#EA580C` |
| 危险 | `#DC2626` |
| 信息（链接/蓝） | `#2563EB` |
| 侧栏底 `--c-sidebar-bg` | `#1E2933`（字 `#CBD5E1` / 激活 `#FFFFFF` / hover `#334155`） |

## 字体
- 标题 `--font-heading`：Sora
- 正文 `--font-body`：Plus Jakarta Sans
- 金额/数字 `--font-mono`：JetBrains Mono（tabular-nums 等宽对齐）
- 中文：Noto Sans SC
- 来源：Google Fonts（CN 镜像），fallback system-ui / 微软雅黑

## 外壳
- 左：深 slate 侧栏，可折叠（220px ↔ 64px 图标栏），Lucide 图标 + 金色选中条（左边框 3px + 淡金底）。
- 顶：白色 header，面包屑 + 右侧用户下拉（退出）。
- 内容：`#F5F7FA` 底，白卡（圆角 12px、细边框、轻阴影）。
- 表格：密集行、sticky 表头、行 hover、金额列等宽右对齐、状态用 NTag 语义色。

## 图表
ECharts（vue-echarts）+ 自定义 'siegpu' 主题（深金 `#B45309` 主、teal/blue 辅）。
- 首页：KPI 卡 + 资金月度趋势（柱/折线）+ 预警。
- 资金池：余额走势（面积）+ 收支构成（柱/饼）。
- 应收：账龄堆叠柱。

## 图标
Lucide (`lucide-vue-next`)，SVG，禁 emoji。统一线性、24px、stroke 1.5。

## 实现
- Naive UI `NConfigProvider` + `themeOverrides` 注入主色/字体/圆角（common 覆盖）。
- CSS 变量在 `src/styles/tokens.css`，`global.css` 接入字体 + 基础排版 + `.num` 等宽类。
- `prefers-reduced-motion`、对比度 ≥4.5:1、focus 可见、触控区 ≥40px。
