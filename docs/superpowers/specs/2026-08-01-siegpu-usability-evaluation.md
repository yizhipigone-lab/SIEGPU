# SIEGPU ERP 终端用户易用性专项评估报告

> 日期：2026-08-01 | 范围：系统实施落地后的全量评估
> 维度：业务流程顺畅性 / 人机交互可引导性 / 上手顺畅性
> 方法：三路并行代码审计（前端 11 个 view + GenericCrud + 路由/菜单配置；后端 21 个 service + 22 个 endpoint + 异常体系；操作手册 + seed/demo 数据），全部结论附代码证据
> 说明：本报告为只读静态分析，未在浏览器实测运行；涉及"页面空白/未配置模块"类结论来自路由表与配置的静态比对

---

## 0. 总体结论

**后端引擎是认真做过的，前端只交付了"看板"，没交付"工作台"。**

后端工作流引擎（推进/回退/埋点/并发锁/权限分层/白名单）和业务自动化（放款自动置换、点亮生成资产、红冲反向记录）质量较高；但向导式工作台的核心交互未落地——**StepDrawer 组件不存在（ProjectWorkspace.vue:73-75 是 TODO）**、工作台跳转映射系统性错误、6 个业务页面是纯只读列表。三者叠加导致：**18 步向导中约一半的步骤，用户在界面上走不通，最终仍要回到"列表页 + 手调 API"的老路**。

按优先级修复 P0 层（§4.1 的 ★1–★4）即可把端到端链路在 UI 上打通；P1 层解决"看得懂"，P2 层解决"用着顺"。

---

## 1. 维度一：业务流程顺畅性

### 1.1 优势

- **向导引擎后端机制完整自洽**：建项目自动建工作流并完成 Step 1（`projects.py:30` → `workflow_service.create_workflow`）；每次完成/跳过/手动完成/推断都写 `StepAuditLog`；`SELECT FOR UPDATE` 防并发（`workflow_service.py:94-98`）；`after_action` 失败只记日志不炸业务事务；completion_check 有表白名单防越权
- **红冲回退设计超预期**：`refresh_all_steps` 能把已 done 但数据被红冲的步骤回退为 pending（`workflow_service.py:215-219`）
- **旧项目兼容**：`infer_workflow` 从存量 24 张业务表反推进度且幂等
- **关键动作自动化程度高**：金租放款一键生成入金流水 + N 期还款计划 + 自动资金置换（`leasing_service.py:91-143`）；点亮同事务生成资产+折旧参数；红冲用反向记录不改原单，SUM 自动抵消
- **Dashboard 待办按角色过滤**，点击"立即处理"直达工作台；金租 9 节点时间线可视化 + 还款逐期确认；利润测算支持"选项目→自动取真实参数"

### 1.2 痛点

| # | 痛点 | 严重程度 | 证据 |
|---|------|---------|------|
| F1 | **抽屉操作整体未实现**：8/18 个 drawer 步骤（流贷/自有入金、预付、采购/销售验收、计费、客户确认、开票核销）在工作台点击只弹"抽屉操作待实现"，后端已下发的 `drawer_schema`/`prefill`/`action_chain` 前端完全未消费 | 高 | `ProjectWorkspace.vue:73-75` TODO；全库无 `StepDrawer` |
| F2 | **"立即处理"跳转大面积落空**：module→路由映射与工作流步骤的 module 值系统性不匹配（单复数错误），`billing→/billing` 路由不存在，约 9-10 步点了看到"未配置该模块" | 高 | `ProjectWorkspace.vue:77` vs `modules.ts` 键（projects/contracts 复数）vs `router/index.ts` |
| F3 | **多个环节 UI 上根本无法操作（流程断点）**：计费无页面无菜单；发票核销无前端调用（Step 17 **永远无法在 UI 完成**）；交付 6 阶段无推进 UI；金租申请创建/节点推进无按钮；销售订单/验收/客户确认三个页面是纯只读列表；盈利测算只算不存（Step 18 永不完成） | 高 | `SalesOrdersView.vue`（还 import 了未使用的 NModal/Plus，半成品痕迹）、`AcceptancesView.vue`、`ConfirmationsView.vue`、`LeasingView.vue`、`ProfitView.vue` |
| F4 | **合同/订单表单要求手填 UUID**："项目 ID""对方 ID""设备型号 ID"纯文本输入，界面无任何地方展示这些 ID，录入错误高发 | 高 | `modules.ts:133-155`；对比 `CapitalView.vue:72` 的项目下拉（好） |
| F5 | **埋点覆盖不全 + 单次只推一步**：销售订单创建、采购订单创建、金租申请创建、盈利场景保存 4 处未挂 `after_action`；且每次只检测 current_step 一步，Step 12 与 Step 14 检测条件相同（都是 `orders.status=已点亮`），点亮后 Step 14 要等下一次动作才闭环——用户感知"做完了进度还卡住" | 中 | `sales_order_service.py`/`order_service.py:24-41`/`leasing_service.py:33-55` 无调用；`workflow_service.py:143-147, 421-423` |
| F6 | **无轮询/自动刷新**：待办与工作台仅 onMounted 加载一次，多人协作下必须手动刷新 | 中 | 全前端 grep 无 `setInterval/poll` |
| F7 | **工作台入口单一**：全系统仅 Dashboard 待办卡片能进工作台，项目列表行无"工作台"链接；财务角色登录后看不到项目入口 | 中 | grep `workspace` 仅 3 处命中；`modules.ts` 项目模块无 detailAction |
| F8 | **资金调配/归还/流水红冲无 UI**：后端 `/allocate`、`/allocations/{id}/return`、`/transactions/{id}/reverse` 齐全，前端只有"记一笔"，用户记错账无法自救；发票页有红冲、资金页没有，口径不一 | 中 | `capital.py` vs `CapitalView.vue`；操作手册 §102 自认"UI 待补" |
| F9 | **15 步自有全款模板不可选**：建项目时不传 template_id，项目表单也无模板选择项，模板体系形同虚设 | 低 | `projects.py:30`、`seed.py:64-68` |
| F10 | **审批链断点**：步骤定义了 `approver_role` 但无任何审批流实现，验收 approve、放款均无审批校验，approver 仅是展示文案；Step 10 doer=approver=FINANCE_DIRECTOR 自审批 | 低 | `workflow_service.py:410-427` vs 全库无审批逻辑 |
| F11 | **两处冗余节点**：Step 12 名不副实（未检测 6 阶段逐项完成，`delivery_stages` 在 `_table_class` 中为 None，检测条件与 Step 14 相同）；"验收管理/客户确认"两个一级菜单页面只读，占导航无操作价值 | 低 | `workflow_service.py:399, 421, 423` |
| F12 | **`completed_by` 从未写入**：时间线无法显示"谁完成的"，操作人只在 audit log 里 | 低 | `_mark_done/skip_step/mark_step_done` 只写 `completed_at` |

---

## 2. 维度二：人机交互可引导性

### 2.1 优势

- **后端错误文案全部中文且业务化**，含下一步指引："订单尚未点亮，无法计费（计费起点=点亮日）"、"发票累计超过合同金额，需总监审批"、"强制跳过必做步骤需要 FINANCE_DIRECTOR 或 ADMIN 权限"；防呆文案齐备（"反向记录不可再红冲"、"已红冲发票不可核销"）
- **不泄露技术细节**：全局 IntegrityError handler 统一映射 409 中文提示，不回原始 SQL
- **命名业务化**：菜单"资金池/金租流程/发票对账/利润测算"，按钮"点亮上线/确认放款/红冲/收款"
- **关键操作有后果预告**：放款前明示"将自动生成 X 期还款计划 + 1 条入金流水"；点亮成功提示"已生成资产 + 月折旧"
- **三态基本齐备**：列表 loading + 空态、工作台 NSpin + "项目暂无工作流"；删除有 NPopconfirm 二次确认
- **智能预填**：还款确认自动带入计划本息；OCR 识别发票自动填表并提示"识别后请人工校验"

### 2.2 痛点

| # | 痛点 | 严重程度 | 证据 |
|---|------|---------|------|
| U1 | **4 个页面错误解析键写错，后端精心写的中文报错永远显示不出来**：读 `e?.response?.data?.message`，但 BusinessError 结构是 `{detail: {code, message}}`——403 的真实原因"需要 FINANCE_DIRECTOR 或 ADMIN 权限"被吞成干巴巴的"标记失败"。共 7 处 | 高 | `ProjectWorkspace.vue:39/49/60/68`、`AcceptancesView.vue:33`、`SalesOrdersView.vue:34`、`ConfirmationsView.vue:31`；对比 `LeasingView.vue:62`/`GenericCrud.vue:83-84` 写法正确 |
| U2 | **红冲无二次确认、无后果说明**：`reverseInvoice` 点击即执行（同文件删除却有 NPopconfirm）；资金侧连红冲入口都没有 | 高 | `InvoicesView.vue:74-79` |
| U3 | **422 校验错误被吞成"保存失败"**：后端无 RequestValidationError handler，FastAPI 默认返回英文 detail 数组，前端取不到 message，用户不知道哪个字段错了 | 中 | `main.py` 只注册 IntegrityError handler |
| U4 | **跳过/标记完成交互粗糙**：跳过用浏览器原生 `prompt('跳过原因：')`，与 Naive UI 体系格格不入；按钮对所有角色显示，点了才被 403（且因 U1 看不到原因）；标记完成的 note 硬编码"手动标记完成"，审计价值低 | 中 | `ProjectWorkspace.vue:54, 65, 127-130` |
| U5 | **表单无前端校验**：所有 NFormItem 无 required/rules，空表单可直提，只能等后端报错兜底 | 中 | `GenericCrud.vue:223-228` |
| U6 | **日期全靠手输 YYYY-MM-DD 文本框**：无 NDatePicker，格式错一个字符就 422；发票收款日期锁死当天，补录历史回款无法表达 | 中 | `CapitalView.vue:84`、`LeasingView.vue:153`、`InvoicesView.vue:67-69` |
| U7 | **角色英文代码裸露给用户**：顶栏、待办卡片、工作台"负责人"均直接显示 `FINANCE_STAFF`，seed 里已有中文 display 但前端没做映射 | 中 | `MainLayout.vue:115`、`Dashboard.vue:71`、`ProjectWorkspace.vue:136` |
| U8 | **静默失败与误报**：ProfitView 项目列表加载失败完全静默；上传解析失败也报"上传成功"；401 直接跳登录页无提示；登录错误一刀切（500/断网也报"用户名或密码错误"） | 低 | `ProfitView.vue:67`、`GenericCrud.vue:101`、`client.ts:15-18`、`Login.vue:22-24` |
| U9 | **步骤状态只用符号**：时间线 tag 仅 `✓/⊘/○`，无"已完成/已跳过/待处理"文字 | 低 | `ProjectWorkspace.vue:161-163` |

---

## 3. 维度三：上手顺畅性

### 3.1 优势

- **操作手册完整且诚实**：端到端剧本（§5 步骤 0-8，明确"建议严格按此顺序"）、"已实现 vs 待办（诚实清单）"、排障表报错文案与代码真实文案一一对应
- **登录页排错引导好**：开发模式直接列出 5 个种子账号；手册预判了"浏览器自动填充旧密码"的真实坑
- **演示数据质量高**：`demo.py` 用真实测算参数（1372 台 5090、金租本金 8.30 亿）跑通全链路且幂等，适合自助摸索
- **视觉辨识规范**：30+ 种状态映射为语义色标签；金额等宽右对齐

### 3.2 痛点

| # | 痛点 | 严重程度 | 证据 |
|---|------|---------|------|
| O1 | **新用户从待办点进来绝大多数步骤走不通**（F1+F2+F3 的上手视角后果）：向导本是降低学习成本的核心设计，目前反而成为"点了没反应/报错"的挫败源 | 高 | 见 §1.2 F1-F3 |
| O2 | **角色不可感知**：菜单对所有角色一模一样，系统内没有"我这个角色该干什么"的任何提示；手册 §4 权限矩阵在系统内无对应物 | 中 | `MainLayout.vue:24-45` |
| O3 | **行业黑话无解释**："点亮""红冲""金租置换""三流对账""等额本息"界面无 tooltip/帮助入口；手册解释散落在正文，首次出现即使用 | 中 | 全库 grep 帮助/术语无命中 |
| O4 | **手册与当前 UI 脱节**：v2.0 手册未提及工作台/待办/模板；§5 步骤 3 仍写"金租 UI 列表/详情待补"（已落地）；§6 速查表缺 5 个新菜单 | 中 | `OPERATION-GUIDE.md` grep 无"工作台" |
| O5 | **demo 数据不可被发现 + 空态无引导**：手册全文无 `app.demo` 字样；新部署环境登录后 Dashboard 全空（KPI 显示 `-`），无任何"第一步该做什么"的引导；空表只有"暂无数据"四个字 | 中 | `Dashboard.vue:65` 无待办时整个卡片消失；`GenericCrud.vue:217` |
| O6 | **登录页账号提示仅开发模式可见**：生产首次使用者无任何账号线索 | 低 | `Login.vue:14, 57` |
| O7 | **对账页合同列显示截断 UUID**：`contract_id.slice(0,8)+'…'`，肉眼无法对应具体合同 | 低 | `InvoicesView.vue:104` |

---

## 4. 优化改进建议（分层，可落地）

### 4.1 P0 — 先修死路（不做这些，向导形同虚设）

| # | 建议 | 对应痛点 |
|---|------|---------|
| ★1 | **实现 `StepDrawer.vue`**：1 个 NDrawer 壳 + 6 个 schema 表单组件（capital_in/capital_out/acceptance/billing_confirm/confirmation/invoice_issue，设计文档 §7.3 已定义）；消费后端已下发的 `drawer_schema`/`prefill`（`{{project_id}}` 提交时替换）/`action_chain`（验收 create→upload→approve 分步链式提交，每步失败显示中文错误并保留已完成子步骤状态）；成功后调 `/refresh` 并 reload | F1、O1 |
| ★2 | **补齐 6 个只读页面的操作能力**：SalesOrdersView 加新增表单；AcceptancesView 加新建+通过/驳回；ConfirmationsView 加确认/争议；LeasingView 加新建申请弹窗与节点推进/卡住按钮；订单详情加 6 阶段推进 action；新建 BillingsView（挂 `/billing` 路由和菜单）；ProfitView 加"保存为场景/设为实际"按钮 | F3 |
| ★3 | **修复工作台跳转映射表**：改为显式查表 `{contract:'/master/contracts', sales_order:'/sales-orders', order:'/master/orders', acceptance:'/acceptances', ...}`，并带 `?project_id=xxx` query 让目标页预填 | F2 |
| ★4 | **统一错误解析**：全局封装 `errMsg(e) = e.response?.data?.detail?.message ?? e.message`，替换 7 处错误用法；后端补 RequestValidationError handler，把字段名+中文 msg 拼成 `detail.message` | U1、U3 |

### 4.2 P1 — 让用户"看得懂"

| # | 建议 | 对应痛点 |
|---|------|---------|
| ★5 | **消灭 UUID 手填**：FieldConfig 增加 `type:'remote-select'` + `optionsEndpoint`，合同/订单的 project_id/party_id/equipment_model_id 改远程下拉（label 显示名称）；对账页合同列改显 contract_no | F4、O7 |
| ★6 | **危险操作加确认与说明**：红冲包 NPopconfirm（"红冲将作废该发票且不可恢复"）；跳过改 NModal+必填原因；标记完成注明"将绕过自动检测，需财务总监权限"并允许填 note；按钮按 `auth.role` 做 v-if 显隐（与后端 require_role 对齐） | U2、U4 |
| ★7 | **角色中文化 + 术语解释**：建 `{FINANCE_STAFF:'财务专员',...}` 映射用于顶栏/待办/工作台；"点亮上线""红冲"等加 NTooltip 释义；顶栏加"?"帮助入口 | U7、O2、O3 |
| ★8 | **补齐埋点 + 循环推进**：sales_order/order/leasing.create_process/profit.save_scenario 各加 3 行 after_action；after_action 改 while 循环推进消除"一步一滞后"；Step 12 的 completion_check 改为检测 delivery_stages 前 5 阶段完成，与 Step 14 点亮区分开 | F5、F11 |
| ★9 | **加核销与资金调配 UI**：发票页行操作加"核销"弹窗（选流水、展示部分核销进度）；资金页加调配/归还/红冲三个入口（端点均已存在） | F3、F8 |

### 4.3 P2 — 让系统"用着顺"

| # | 建议 | 对应痛点 |
|---|------|---------|
| ★10 | **工作台入口与刷新**：项目列表行加"工作台"按钮；Dashboard 待办加 30s 静默轮询；操作成功后自动 reload | F6、F7 |
| ★11 | **表单体验**：必填字段加红星+前端校验；日期统一换 NDatePicker（value-format YYYY-MM-DD）；发票收款改弹窗选日期默认今天 | U5、U6 |
| ★12 | **空态与新手引导**：Dashboard 首 run 显示引导卡（①建主数据 ②建项目自动生向导 ③`python -m app.demo` 载入演示数据）；空表加"点右上角『新增』创建第一条"；步骤 tag 加文字标签 | O5、U9 |
| ★13 | **会话与登录**：401 跳转前提示"登录已过期"；登录按 status 区分"账号密码错误"与"服务异常"；账号提示加 `VITE_SHOW_DEMO_HINT` 开关 | U8、O6 |
| ★14 | **模板与收口**：建项目表单加"流程模板"下拉（后端透传 template_id）；工作台时间线显示 completed_by（后端写入+前端渲染） | F9、F12 |
| ★15 | **手册更新**：补 v3.2 工作台章节（用法/两个预置模板/demo 命令）；修正"金租 UI 待补"过时描述；§6 速查表补 5 个新菜单 | O4 |

### 4.4 待业务确认（不擅自改）

- **Step 10 自审批**：doer=approver=FINANCE_DIRECTOR，违背职责分离——doer 是否应改为 FINANCE_STAFF？（设计文档 §12 风险 9 已挂起）
- **审批流是否实现**：approver_role 目前仅展示文案，验收/放款无审批校验——v1 保持现状还是补审批流？

---

## 5. 分层摘要

| 层 | 结论 |
|---|------|
| **优势层** | 后端引擎（推进/回退/幂等/权限）与业务自动化（置换/资产/红冲）扎实；中文业务化报错体系完整；手册诚实、demo 数据质量高 |
| **断点层（P0）** | StepDrawer 未实现 + 跳转映射错误 + 6 个只读页面 + 错误解析键错误 → 18 步约一半在 UI 走不通，错误原因被吞 |
| **理解层（P1）** | UUID 手填、角色英文裸露、术语无解释、危险操作无确认 → 用户"看不懂、不敢点" |
| **顺畅层（P2）** | 无轮询、入口单一、日期手输、空态无引导、手册滞后 → 日常使用的摩擦点 |

**一句话**：优先落地 ★1–★4，端到端流程即可在界面闭环；再做 ★5–★9 让财务/采购/交付各角色"看得懂、敢操作"；★10–★15 作为体验收尾与文档同步。
