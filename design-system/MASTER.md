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

---

## 附录 A · v3.2 向导式工作台与多项目组件规范（2026-08-01 补）

> 背景：v3.2 实现先行，本附录把已上线的新组件沉淀为规范，新页面必须照此执行。

### A.1 项目工作台（ProjectWorkspace）

- **三栏布局**：顶栏进度条 / 左栏步骤时间线 / 右栏当前步骤操作区。
- **进度点 4 色语义**：绿 success=已完成、蓝 info=进行中、灰 default=待处理、黄 warning=已跳过；与 `statusTagType` 同源。
- **时间线**：每步显示 步骤名 + 状态文字（禁纯符号）+ 执行角色中文名 + 完成日期/操作人（completed_by 可空）。
- **当前步骤卡**：负责人/审批人中文角色 tag；「立即处理」主按钮；「标记完成/跳过」按角色显隐（FINANCE_DIRECTOR/ADMIN 可见）。

### A.2 StepDrawer 抽屉

- 右侧 NDrawer，**注册表模式**（drawer_schema → 表单组件），非 schema 驱动。
- 预填：`{{project_id}}` 提交时替换，其余字面值直填；提交成功自动 `/refresh` 并刷新工作台。
- **链式分步状态条**（如验收 create→upload→approve）：每子步显示 待执行/执行中/已完成/已跳过/失败；失败显示该步中文错误、保留已完成子步、重试仅续跑未完成子步。

### A.3 多项目页面

- **/portfolio 项目总览**：表格 = 项目 / 当前步骤（Step N—中文名）/ 进度条 / 状态 tag / 待办角色 / 停滞天数（>7 天 warning、>14 天 error）；行点击进工作台，行 hover 手型。
- **/comparison 项目对比**：全列可排序，空值排最后；回款率 ≥80% success / ≥50% warning / 其余 error；逾期笔数 >0 用 error tag；金额一律 `money()` 千分位 + `.num` 等宽右对齐。

### A.4 交互与工程约定（全站统一）

| 约定 | 实现 |
|---|---|
| 错误提示 | `utils/errMsg.ts` 统一解析（detail.message → 字符串 → 422 数组中文化 → 兜底），禁止再写 `data?.message` |
| 角色显示 | `utils/role.ts` roleName()，任何角色码不得裸露给用户 |
| 远程下拉 | FieldConfig.remoteOptions（label 显示名称、value 为 id），禁止手填 UUID |
| 日期 | NDatePicker 绑时间戳，`utils/format.ts` 的 tsToYmd/ymdToTs 互转提交（本仓 naive-ui 版本不接受 value-format 字符串） |
| 危险操作 | NPopconfirm + 后果说明文案（红冲/跳过/标记完成/删除）；跳过失原因为必填 |
| 术语解释 | 顶栏「?」NPopover 术语表 + 关键按钮 NTooltip（点亮/红冲/核销/调配） |
| 空态 | 列表「暂无数据，点右上角『新增』创建第一条」；首页首 run 三步引导卡 |
| 待办刷新 | 首页待办 30s 静默轮询（无 loading 闪烁），工作台手动「刷新进度」 |
| 新增菜单图标 | FolderKanban=项目总览、GitCompareArrows=项目对比、Receipt=计费管理（Lucide 线性 1.5 stroke 不变） |
