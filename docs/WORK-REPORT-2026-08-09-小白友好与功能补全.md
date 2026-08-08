# SIEGPU 算力租赁 ERP — 小白友好度 + 功能补全（8 项 / 3 波）工作汇报

> **生成时间**：2026-08-09
> **汇报范围**：`abstract-shimmying-crown.md` 计划的 8 项 roadmap（U1/U2/U3/U4 + F1/F2/F3/F4），分 3 波连续做完
> **当前分支**：`main`　**工作区**：大量未提交改动，**未 git commit（用户未授权）**
> **一句话状态**：8 项全部端到端验证通过（pytest **246 绿** / e2e **44 绿** / 浏览器逐项真点）；小白从「看不懂、不会填、走不通」到「有引导、有提示、能出错提醒、能一键出单」。

---

## 0. 状态快照（先看这张表）

| 波 | 项 | 性质 | 状态 | 验证 |
|---|---|---|---|---|
| 一 | **U3** 首页快捷入口 | 纯前端 | ✅ | 浏览器（procurement/finance 首页出现新按钮） |
| 一 | **U4** 空状态引导 + 危险确认 | 纯前端 | ✅ | 浏览器（空数据引导文案 + 删除/红冲后果确认） |
| 一 | **U1** 流程进度条（详情抽屉） | 纯前端 | ✅ | 浏览器（合同/项目详情顶部 11 步进度条） |
| 一 | **U2** 术语大白话 + 错误中文化 | 纯前端 | ✅ | 浏览器（术语问号气泡 + 报错中文） |
| 二 | **F3** 客户对账单 | 前后端 | ✅ | pytest + 浏览器（选客户看四值与明细勾稽） |
| 二 | **F2** 设备可租库存看板 | 前后端 | ✅ | pytest + 浏览器（按型号：可租/在租/待交付） |
| 二 | **U2** 表单即时校验铺开 | 纯前端 | ✅ | 浏览器（金额≤0/数量非正/百分比>1 即时标黄） |
| 三 | **F1** 消息提醒中心（应用内） | 新框架 | ✅ | pytest 9 + 浏览器（铃铛红点→列表→已读→跳转） |
| 三 | **F4** 合同/发票 PDF | 新依赖 | ✅ | pytest 4 + 浏览器（双向下载验证 %PDF-1.7） |

**验证基线**：
| 维度 | 数量 | 命令 |
|---|---|---|
| 后端单测 | **246 passed**（233 基线 + F1 9 + F4 4） | `docker compose exec backend pytest app/tests/ -q` |
| E2E | **44 passed**（0 回归） | `cd e2e && npm test` |
| 前端类型 + 构建 | 绿 | `cd frontend && npm run type-check && npm run build` |
| alembic 0009 双向 | ✅ upgrade/downgrade 可逆 | throwaway 库往返 |

---

## 0.5 评审修正记录（2026-08-09 评审后订正）

用户评审本汇报后点名 **1 处实质缺漏 + 2 处口径不准**，已逐一核实并处理：

| 评审意见 | 核实结果 | 处理 |
|---|---|---|
| ❌ **U4 只做了 4/8**（Devices/Acceptances/Confirmations/SalesOrders 全是裸表格） | 属实。初版 grep 只查 kebab `<n-data-table>`，漏了 4 个 **camelCase `<n-dataTable>`**（naive-ui 同一组件，两种写法） | **补代码**：4 个 view 全加 `#empty` 引导，**已 8/8**；DevicesView 筛「直租」实测 EmptyState 渲染（`.n-data-table-empty` + 引导文案，截图 `u4-devices-emptystate.png`） |
| ⚠️ **F2 是 inner join 不是 outerjoin**（device_service.py:124） | 属实。报告误写 outerjoin，代码实为 inner join | **问用户**：维持 inner join（看板聚焦「可租库存」，零库存型号是噪音）。**仅订正文档**，不改代码 |
| ⚠️ **F1 去重是「永久」不是「当天」**（notification_service.py:30-37） | 属实。报告写「当天只一条」，代码实为永久去重（`_dedup_exists`） | **问用户**：改真·**当天只一条、每日重发**。**改代码** `_dedup_exists`→`_sent_today`（UTC+8 自然日）+ 加测试 `test_dedup_is_daily_not_permanent`（pytest 245→**246**） |

> 评审其余重点核实为真：基线 245 = 225 + F3(4) + F2(4) + F1(8) + F4(4) 全对、8 项功能真实落地、可验证声明 90%+ 属实。订正后（F1 +1 测试）实跑 pytest **246** / e2e **44** 全绿。

---

## 1. 为什么做（背景）

SIEGPU 算力租赁 ERP 业务链路已 90% 打通（立项→采购→金租→验收→设备→交付→计费→开票→回款→折旧→售后回租），但两个短板让**非技术用户用不动**：

1. **小白门槛高**：专业术语（金租表外/残值率/IRR/红冲/点亮上线）、流程走到哪不直观、空页面无引导、填错才报错且报错是技术码。
2. **功能缺口**：到期/逾期没人主动提醒（算力租赁按期，忘回收=资产流失）、设备可租库存看不出、客户对账要手动对三张表、合同发票不能一键出 PDF。

用户勾选 8 项补齐，并决定：**F1 仅做应用内铃铛+红点**（零外部依赖，不引邮件/企微）、**安全问题全搁置**（改密/权限拦截/审计 UI）、**分 3 波逐波做每波验证**，后因「开始全部做完」连续推完三波。

---

## 2. 三波工作明细

### 第一波 — UX 体验打底（纯前端，零外部依赖）

#### U3 首页常用操作快捷入口
- **单一事实源** `frontend/src/utils/roleGuide.ts` 的 `ROLE_GUIDE.*.quickActions`：给 PROCUREMENT 加「新建项目」（`/master/projects`）、FINANCE_STAFF 加「记流水」（`/capital`）+「记采购订单」（`/master/orders`）。
- **约束遵守**：每个 route 先 grep 确认在 `roleMenu.ts` 该角色白名单内；admin/cfo 走原首页（`seesOriginalDashboard` 返 true）不动。
- **验证**：procurement/finance 账号登录，首页快捷区出现新按钮且点击直达对应页。

#### U4 空状态引导 + 危险操作确认
- **抽组件** `frontend/src/components/EmptyState.vue`（图标 + 文案 + 可选 CTA），给所有独立 view（Capital/Invoices/Billings/Devices/Leasing/Acceptances/Confirmations/SalesOrders）的 `<n-data-table>` 加 `#empty` 引导文案（告诉小白「这里还没数据，去哪创建」）。
  - ⚠️ **覆盖订正**：初版只做了 4 个 kebab 写法 `<n-data-table>` 的 view（Capital/Invoices/Billings/Leasing），漏了 4 个 **camelCase 写法 `<n-dataTable>`** 的 view（Devices/Acceptances/Confirmations/SalesOrders）——naive-ui 两者是同一组件，但早前 grep 只查 kebab 没覆盖 camelCase，导致 4 个裸表格漏接。2026-08-09 评审点名「U4 只做了 4/8」后，补齐这 4 个 view 的 `#empty` 引导。**已 8/8 全接**，并在 DevicesView 实测：金租模式筛「直租」过滤掉所有表内自有设备 → 主表出现 `.n-data-table-empty` 节点 + 引导文案「还没有设备，订单「点亮上线」后设备会自动入库…」（见截图 `u4-devices-emptystate.png`）。
- **危险确认加后果**：`GenericCrud.vue` 删除确认 `'确认删除？'` → `'删除后不可撤销，关联的业务数据可能受影响，确认删除？'`；各独立 view 的 NPopconfirm（红冲/作废/放款）统一加后果说明。

#### U1 流程进度条（下沉到详情抽屉）
- **抽组件** `frontend/src/components/WorkflowProgress.vue`（入参 projectId，内部调 `GET /api/workflows/{id}`，NSteps 渲染 11 步 + 高亮当前步 + 「下一步：XX（由 XX 角色处理）」）。
- `GenericCrud.vue` 详情抽屉顶部：当 `detailRow.project_id` 存在时挂进度条（非项目实体不强求）。
- 清理 `ProjectWorkspace.vue` 的死导入（NSteps/NStep 导了没用）。

#### U2 术语大白话 + 错误中文化
- **错误中文化**：`GenericCrud.vue` 三处绕过 `errMsg` 的改回（advanceStage/del/download 的写死中文 → 优先 `errMsg(e)`）；扩 `utils/errMsg.ts` 的 `FIELD_CN` 覆盖新字段。
- **术语 tooltip**：`config/modules.ts` 的 `FieldConfig` 加可选 `hint`；GenericCrud 表单 NFormItem 对有 hint 的字段加问号气泡；术语表建在 `frontend/src/utils/glossary.ts`（残值率→「租期结束时设备剩余价值占比，一般填 0.10 即 10%」、年利率、IRR、金租、红冲、点亮上线、表内/表外等）。

**第一波验证**：`npm run type-check && npm run build`（绿）→ `docker compose build frontend && up -d frontend` → 浏览器逐项真点 → e2e 44 回归不破。

---

### 第二波 — 中等功能（前后端，复用现成算法）

#### F3 客户对账单
- **复用** `invoice_service.reconciliation`（三流对账算法 100% 复用），仅把 group 维度从 contract 改成 customer（取该客户所有 `Contract(type='SALES', party_type='customer', party_id=X)` 跑同样三个 sum）。
- **新增** 后端 `GET /api/reports/customer-statement?customer_id=X`（`report_service.py`，返回计费额/已开票/已回款/欠款/明细列表）；前端 `CustomerStatementView.vue`（客户下拉 + 四 KPI 卡 + 明细表）+ 路由 + roleMenu（FINANCE_STAFF/ADMIN/cfo）。
- **绕开隐性 bug**：不用 `receivables_aging`（依赖未写入的「已收款」状态），统一用 reconciliation 的 `Invoice.paid_date/matched_amount` 口径。
- **测试** `test_customer_statement.py`。

#### F2 设备可租库存看板
- **口径定义**：`在租 = exists(未红冲 Billing where device_id=X)`；`可租 = device.status=='点亮验收' AND not exists(Billing) AND ownership=='表内自有'`；`待交付 = status in (订货/在途/到货/己方压测/上架/客户压测)`；表外金租/转售不参与自营出租。
- **复用** `device_service._assert_light_rework_safe` 的 Billing 存在性子查询模式。
- **新增** 后端 `GET /api/devices/inventory-summary`（按 EquipmentModel **inner join** Device 聚合——零库存型号不上看板）；前端 `DevicesView.vue` 顶部加聚合卡片区（按型号：可租/在租/待交付）。
  - ⚠️ **口径订正**：本节早前误写「outerjoin」。实际 `device_service.py:124` 是 **inner join**，型号目录里「一台设备都没有」的型号不显示。2026-08-09 评审点名后与用户确认：**维持 inner join**（看板叫「可租库存」，零库存型号对销售/运营是噪音；当前行为已过 e2e）。故仅订正文档，不改代码。
- **测试** `test_device_inventory.py`（含红冲剔除/表外剔除）。

#### U2 表单即时校验铺开
- `config/modules.ts` 的 `FieldConfig` 加可选 `validate`；`frontend/src/utils/validators.ts`（`positiveAmount` 金额>0 / `positiveInt` 正整数 / `decimalRate` 百分比≤1）。
- GenericCrud 表单 number 字段加 `:status="warning"` 即时校验（非阻塞，只标黄提醒，真正非法值仍由后端拒绝）。

**第二波验证**：pytest（新增 statement + inventory 用例，233 全绿）+ e2e 44 + 浏览器 + alembic 无新 migration（本波不加字段）。

---

### 第三波 — 重（新框架 / 新依赖）

#### F1 消息提醒中心（仅应用内）
- **持久化**：新 `Notification` model + **手写** alembic `0009_notifications`（`notifications(id, user_id FK, kind, ref_type, ref_id, title, body, level, read_at, created_at)`，复用 TimestampMixin）+ `schema.sql` 双写。**0009 必须手写**——`alembic check` 因历史 `fk_inv_billing` DEFERRED 漂移已 FAILED，autogenerate 会把历史漂移卷进新迁移。upgrade/downgrade 双向已 throwaway 库往返验证。
- **service** `notification_service.py`：
  - `scan_and_persist(db)`：调 `alert_service.compute_alerts`（实有 **8 类规则**：还款逾期/调配逾期/金租放款不符/金租放款延迟/资金池不足/交付停滞/合同即将到期/项目流程停滞），fan-out 给所有 active 用户，**当天幂等去重**（`_sent_today`：同 user×kind×ref_id 当天（Asia/Shanghai 自然日）已写过则跳过，ref_id=None 用 `.is_(None)`），**不 commit**（service 不 commit 是项目铁律，endpoint/scheduler commit）。
  - ⚠️ **去重口径订正**：本节早前写「当天只一条」，但初版代码实为**永久去重**（`_dedup_exists`：同 user×kind×ref_id 只要历史存在过就跳过）。2026-08-09 评审点名「永久去重会让用户忽略一次后再也不提醒 → 到期/逾期资产流失，与 F1 初衷相悖」后，与用户确认改为真·**当天只一条、每日重发**：当天多次扫描只写一条；次日若底层告警条件仍在（`compute_alerts` 仍产出）会再发一条，直到底层条件消除（发票付清/合同回收）。时区用固定 UTC+8（中国无夏令时，避开 tzdata 依赖）。
  - `list_for_user`（未读优先 + unread_count）/ `mark_read`（只改自己的）/ `mark_all_read`（bulk UPDATE）。
- **定时扫描**：引 `APScheduler`。`main.py` 用 `@asynccontextmanager lifespan`（`on_event` 已弃用），startup 起 `BackgroundScheduler`，每日 **09:07**（避开整点）调 `scan_and_persist` + commit；shutdown `scheduler.shutdown()`。jobstore 内存（一期，重启丢未读可接受）。
- **端点**：`GET /api/notifications`（当前用户未读+近期）/ `POST /api/notifications/{id}/read` / `POST /api/notifications/read-all`（后两者 commit）。
- **前端** `MainLayout.vue` 顶栏加 `<n-badge>` 铃铛 + `<n-popover>` 列表（30s 轮询拉未读数，复用 Dashboard 轮询模式）；点击标记已读 + 跳转对应 ref（repayment/capital→/capital、leasing→/leasing、delivery→/devices、contract→/master/contracts、project→/portfolio）；高危红/警告橙/提示蓝三级配色。
- **测试** `test_notification_service.py` **9 用例**：扫描 fan-out + 当天去重 / 新 ref_id 触发新行 / **跨天重发（昨日同条今日再扫应再发一条，证非永久去重）** / inactive 排除 / 列表未读优先 + 计数 / mark_read 只改自己 / mark_all_read / 用户隔离 / 无告警返零。

#### F4 合同/发票 PDF 生成
- **依赖** `requirements.txt` 加 `jinja2>=3.1` + `weasyprint>=62`；`Dockerfile` apt 装 `libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 libffi-dev fonts-noto-cjk`（weasyprint 系统依赖 + 中文字体）。
  - ⚠️ **踩坑**：`libgdk-pixbuf2.0-0`（2.0 后杠）在 Debian bookworm 不存在，正确名 `libgdk-pixbuf-2.0-0`（2.0 前杠），apt exit 100 已修。
- **service** `pdf_service.py`：
  - `_money(d)`（None→"—"；否则 `￥{Decimal(d):,.2f}` 千分位）/ `_split_tax(amount, tax_rate)`（拆不含税 + 税额）/ `_party_name(db, party_type, party_id)`（customer→Customer.name / supplier→Supplier.name / 已删除→「（客户/供应商已删除）」）。
  - `render_contract_pdf(db, contract_id) -> BytesIO`：404 守门（BusinessError 404）；标题按 type（SALES→「算力设备租赁合同」/ PURCHASE→「算力设备采购合同」）；jinja2 渲染 `contract.html` → weasyprint.write_pdf。
  - `render_invoice_pdf(db, invoice_id) -> BytesIO`：同理；balance = amount - matched_amount；标题按 direction（RECEIVABLE→「销售发票/账单」/ PAYABLE→「购进发票/账单」）。
- **模板** `app/templates/contract.html`（@page A4 / Noto Sans CJK SC / brand + 合同编号 + 生成日期 / parties 甲乙方 / terms 表格含税/不含税/增值税/月租/期限/状态 / 三条款 / 双方盖章区 / 脚注）、`invoice.html`（同设计系统 / 收付款方 / meta 项目+开票日+到期日 / amt 表含税/不含税/增值税/已收已付/尚欠待付 / 提示 callout / 脚注）。
- **端点** `GET /api/contracts/{id}/pdf` + `GET /api/invoices/{id}/pdf`（StreamingResponse, media_type=application/pdf, Content-Disposition attachment）。**实时生成不落库**（避免与扫描件 file_path 混淆）。
- **前端** `modules.ts` Contract 加 `pdfExport: true`（CrudConfig 新增 `pdfExport?: boolean` 标志）；`GenericCrud.vue` 操作列按标志加 FileText 图标按钮（blob 下载，范式同 exportData）；`InvoicesView.vue` 操作列加「PDF」文字按钮（blob 下载，新写——InvoicesView 原无任何导出代码）。
- **测试** `test_pdf_service.py` **4 用例**：合同 PDF 非空且 %PDF 头 / 发票 PDF 同 / 合同 404 / 发票 404。

**第三波验证**：pytest 全量 **246 passed** + alembic 0009 双向 + Dockerfile build 成功 + 浏览器铃铛红点全链路 + PDF 双向下载。

---

## 3. 浏览器端到端验证证据（铁律：后端跑通不是终点）

| 项 | 验证动作 | 证据 |
|---|---|---|
| F1 铃铛 | 造逾期数据 → 铃铛红点(3) → 点列表 → 标记已读 → 跳转 /capital | 后端 read_at 已写、未读 3→2→0、badge 隐藏（`badgeSupVisible: false`） |
| F4 合同 PDF | 合同页点「导出PDF」 | 下载 `合同-283cc4c0.pdf`，**399003 字节 %PDF-1.7** |
| F4 发票 PDF | 发票页点「PDF」 | 下载 `发票-SI-2026-07.pdf`，**389659 字节 %PDF-1.7** |
| F4 排版 | 合同 PDF 转图 analyze_image + 发票 PDF pymupdf 抽文本 | CJK 全可读、金额 `￥830,060,000.00` 千分位、双方/条款/盖章区结构完整、无溢出截断 |
| U1-U4/F2/F3 | 逐角色登录真点 | 见各波验证节 |

---

## 4. 新增依赖与基础设施变更

| 变更 | 文件 | 说明 |
|---|---|---|
| APScheduler | `backend/requirements.txt`（`apscheduler>=3.10`） | F1 定时扫描，内存 jobstore |
| jinja2 + weasyprint | `backend/requirements.txt` | F4 PDF 渲染 |
| 系统库 + 中文字体 | `backend/Dockerfile` | libpango/libcairo/libgdk-pixbuf + fonts-noto-cjk |
| notifications 表 | `alembic/0009_notifications.py` + `db/schema.sql` 双写 | F1 持久化，可逆 |

---

## 5. 新增/修改文件清单

**后端新增**
- `app/models/notification.py`、`app/services/notification_service.py`、`app/services/pdf_service.py`
- `app/api/v1/endpoints/notifications.py`
- `app/templates/contract.html`、`app/templates/invoice.html`
- `app/tests/test_notification_service.py`（9）、`test_pdf_service.py`（4）、`test_customer_statement.py`、`test_device_inventory.py`
- `alembic/versions/0009_notifications.py`

**后端修改**：`main.py`（lifespan + scheduler + notifications 路由）、`requirements.txt`、`Dockerfile`、`db/schema.sql`、`services/report_service.py`（customer-statement）、`services/device_service.py`（inventory-summary）、`api/v1/endpoints/reports.py`、`api/v1/endpoints/devices.py`、`api/v1/endpoints/contracts.py`（+pdf）、`api/v1/endpoints/invoices.py`（+pdf）、`services/alert_service.py`（规则扩展）

**前端新增**
- `components/EmptyState.vue`、`components/WorkflowProgress.vue`
- `utils/glossary.ts`、`utils/validators.ts`、`utils/roleGuide.ts`、`utils/roleMenu.ts`
- `views/CustomerStatementView.vue`

**前端修改**：`layouts/MainLayout.vue`（铃铛）、`views/InvoicesView.vue`（PDF 按钮）、`views/DevicesView.vue`（看板卡）、`components/GenericCrud.vue`（进度条/hint/即时校验/PDF 按钮/删除确认/errMsg）、`config/modules.ts`（pdfExport + hint + validate）、`router/index.ts`（对账单路由）、`utils/errMsg.ts`、`utils/format.ts`

---

## 6. 铁律遵守记录

| 铁律 | 本轮执行 |
|---|---|
| 🚫 不 git commit | ✅ 全部留工作区，`git diff --stat` 评估 |
| 端到端验证铁律 | ✅ 8 项全部浏览器真点，PDF 双向下载验 %PDF 头 |
| 分析必须验证不猜测 | ✅ 发票 PDF 用 pymupdf 抽文本确认 CJK（不靠 CDN 图片猜测） |
| Docker 无 source mount | ✅ 每次前端改 `build frontend && up -d frontend` |
| schema 双写 + 可逆 | ✅ 0009 alembic + schema.sql 双写，双向往返验证 |
| 不破坏现有功能 | ✅ cfo 菜单不收紧（e2e cfo 全过）、Dashboard 待办卡保「待处理」（wizard-workspace 7 子测全过）、GenericCrud 改前盘点 8 依赖模块 |
| service 不 commit | ✅ notification_service 不 commit，endpoint/scheduler commit（db fixture 回滚不被破坏） |

---

## 7. 待办与下一步

### 7.1 本次搁置项（用户决定）
- **安全问题全搁置**：UX-1 API 权限拦截 / UX-2 强制改密 / UX-4 审计查看 UI（见 `WORK-REPORT-2026-08-08.md` §5.1）
- **F1 外部通知搁置**：仅应用内铃铛，未接邮件/企微（用户排除）
- **设备租赁到期**：Device 无 `lease_end_date`，一期用合同到期覆盖，记入未来项

### 7.2 设计债（已记录，未排期）
- F1 jobstore 内存：重启丢未读，如需持久后续换 `SQLAlchemyJobStore`
- F4 PDF 不提供模板自定义（一期固定模板，二期可加 logo/页眉配置）
- e2e 未给新页（对账单/设备看板）加 journey（仅回归不破，未加正向 journey）

### 7.3 一期收尾
- W9-10 联调回归 + 一期终审

---

## 8. 运行 / 验证 / 账号速查

```bash
# 起全栈
docker compose up -d

# 后端测试（246）
docker compose exec backend pytest app/tests/ -q

# 前端类型 + 构建
cd frontend && npm run type-check && npm run build

# e2e（44）
cd e2e && npm test
```

**账号**（密码统一 `sie123`）：admin(ADMIN) / cfo(FINANCE_DIRECTOR) / buyer(PROCUREMENT) / delivery(DELIVERY) / finance(FINANCE_STAFF)

---

> 本汇报由 2026-08-09 会话生成，8 项全部经端到端验证。pytest 246 / e2e 44 实跑确认；F1 alembic 0009 双向 + F4 PDF %PDF 头一手验证。**2026-08-09 评审后已按评审意见订正 U4（补齐 4 view 至 8/8）/ F2（inner join 口径）/ F1（永久去重改当天重发）三处**。配套基线报告见 `docs/WORK-REPORT-2026-08-08.md`。
