# SIEGPU 测试缺陷清单（2026-08-28 定稿）

> 来源：财务/交付线测试人员 23 条反馈 → 对仓库逐行代码核查（6 路子代理分线核对 + 主代理交叉验证 + 到期日空串实测）
> 判定口径：**属实** = 现象与代码一致；**部分属实** = 现象真实但细节/机制与描述有出入；**失实** = 现象不存在
> 统计：11 属实 / 12 部分属实 / 0 失实
> 重要背景：仓库现有 pytest 517 / e2e 73 全绿，但**测试锁的是"实现符合内部裁定"，不是"符合业务习惯"**——多条有争议行为（D2 预付款单源、硬门4 开票前置、开票驱动收入确认、放款入池模型、置换写死放款日）都被测试钉死。修这些条目的同时必须更新对应测试。

## 修复进度（2026-08-28 第二轮）

| 阶段 | 状态 | 验证 |
|---|---|---|
| S1 状态机报错可读化 + 前端不吞错 + 弹窗预筛 | ✅ | e2e `s1-advance-error.spec.ts` 红→绿 |
| S2 验收日期可录 + 验收设备勾稽 + PATCH | ✅ | `test_acceptance_service.py` 8 passed |
| S3 预付款台账收敛（表+落账+设备自动落账+必填供应商/合同+期初引导+dim8 勾稽） | ✅ | 全量 pytest 552 passed；e2e `capital-pools`/`reconciliation-center` 更新后绿 |
| S4 上传失败反馈 + OCR PDF 显式拒绝 + 图片限定 | ✅ | 前端 build ✓；`@error` 回调已加 |
| S5 计费挂销售订单 + 按单汇总出单（K4 三分支） | ✅ | `test_sales_order_billing.py` 4 passed（汇总/未点亮拦截/dup-check/防双计） |
| S6 门4 报错升级 + 收入确认页说明 | ✅ | 报错带跳转引导；前端页头更新 |
| S7 审批中心按 biz_type 分组 + 收入确认页行内审批 | ✅ | 前端 build ✓ |
| S8 直付双流水 + 置换归还日可指定 | ✅ | `test_disbursement_mode.py` 3 passed；迁移 0030 |
| S9 对账单当期口径 | ✅ | `test_customer_statement.py` 当期用例 passed |
| S10 还款计划可调（Σ≤放款额校验） | ✅ | `test_repayment_service.py` 5 passed |
| S11 主数据字段 + 银行授信使用 | ✅ | `test_capital_service.py` 授信用例 passed；迁移 0029 |
| S12 导入模版/行距/金租编辑作废/到期日移除 | ✅ | `test_leasing_service.py` 编辑作废用例 passed；迁移 0031 |
| S13 全量回归 | 🔄 进行中 | pytest **575 passed**；全量 e2e 跑批中 |

> 途中发现：仓库存在 2026-08-27 架构拆分（device_service 拆 facade + device_crud/device_stage_machine/device_batch/device_asset_sync），钩子落在 device_crud。

---

## 23 条逐条验证记录（S13 收口，2026-08-28）

| # | 缺陷 | 判定 | 修复状态 | 验证证据 |
|---|---|---|---|---|
| 1 | 附件上传无反应 | 部分属实 | ✅ | GenericCrud + InvoicesView 补 `@error` 回调（失败可见，含原因）；前端 build ✓ |
| 2 | 设备导入无模版 | 属实 | ✅ | `GET /excel/devices-template`（列说明+示例）；导入弹窗「下载导入模版」 |
| 3 | 设备清单行间距 | 属实(体验) | ✅ | 表格加 `size="small"` |
| 4 | 设备推进验收失败 | 属实 | ✅ | 前端透传后端具体原因 + 弹窗按状态机预筛 + 唯一合法状态自动选中；e2e `s1-advance-error` 红→绿 |
| 5 | 验收与设备不关联、日期默认当天 | 属实 | ✅ | create 接受日期、approve 可覆盖、PATCH 带状态守卫、前端日期控件+批次设备勾稽；`test_acceptance_service` 8 passed |
| 6 | 预付款台账来源错、无时间 | 属实 | ✅ | `prepayments` 表单源（日期/供应商/合同/幂等键）；手工预付同事务落账；设备登记自动落账；结转双写；台账页新列；`test_prepayment`/`test_capital_service` passed |
| 7 | 付款管控记收入确认审批 | 部分属实 | ✅ | 审批中心按 biz_type 分组；收入确认页行内通过/驳回；前端 build ✓ |
| 8 | 自有池无初始余额拦预付 | 属实 | ✅ | 「期初建账（自有入金）」入口；余额不足报错带引导；`test_capital_service` passed |
| 9 | 预付无供应商/采购合同 | 属实 | ✅ | `PrepaymentCreate` supplier/contract 必填；预付弹窗下拉；e2e `capital-pools` 更新后绿 |
| 10 | 金租申请无法修改/作废 | 属实 | ✅ | `PATCH /processes/{id}` + `POST /processes/{id}/void`（仅进行中未放款）+ 前端按钮；迁移 0031 CHECK 扩「已作废」；`test_leasing_service` passed |
| 11 | 还款计划自动生成不可调 | 部分属实 | ✅ | `PATCH /repayments/{id}/plan`（Σ本金≤放款总额校验，已确认禁改）+ 前端「调整计划」；`test_repayment_service` 5 passed |
| 12 | 金租放款记入池流水 | 属实 | ✅ | 放款 `mode`（入池/直付）；直付=负债入账 IN+付款 OUT 双流水（LEASING 池恒0，K5 取数）；`test_disbursement_mode` passed |
| 13 | 放款自动冲销、日期写死 | 部分属实 | ✅ | `replacement_date` 可指定（缺省放款日）；置换归还回填原付款 bank_id（K6）；`test_disbursement_mode` passed |
| 14 | 计费挂在采购订单 | 部分属实 | ✅ | `POST /billings/sales-order`（销售订单汇总出单）；计费页「按销售订单计费」+ 列表显示销售订单号；`test_sales_order_billing` passed |
| 15 | 只能按台计费 | 部分属实 | ✅ | 按销售订单/批次整体出单（K4 三分支：批次汇总/非批次 total_monthly_rent/防双计跳过） |
| 16 | 按台计费走不通 | 属实 | ✅ | 未点亮报错透传具体原因（"设备尚未点亮验收"）+ 计费弹窗前置提示（同 #4） |
| 17 | 确认/对账无法测试 | 部分属实 | ✅ | 计费链打通（#14/#15）→ 确认单可建可确认 → 门4 开票；e2e 全链跑通 |
| 18 | 对账单是累计非当期 | 属实 | ✅ | `customer-statement?period=YYYY-MM` 当期口径 + 前端「累计/当期」切换；`test_customer_statement` passed |
| 19 | OCR 不可用、到期日必填 | 部分属实 | ✅ | OCR 仅图片（PDF 显式拒绝）+ 上传失败可见；到期日字段移除 + 后端空串 validator（`''`→None）；`test_invoice_create_empty_string_dates` passed |
| 20 | 发票被无对账单拦 | 属实 | ✅ | 门4 保留（业务合理），报错升级带跳转引导；`test_hard_gates` 保留绿 |
| 21 | 收入确认无法自动生成 | 部分属实 | ✅ | 维持开票驱动（口径确认）；页面明示"开票即自动生成草稿"+行内审批；链路经 #14/#15 打通 |
| 22 | 供应商/客户字段少 | 属实 | ✅ | 税号/开票抬头/开户行/账号/地址（供应商），客户同款；schema 输出补全 + 表单字段；迁移 0029 |
| 23 | 银行授信无使用/余额 | 属实 | ✅ | `bank_credit_usage` 聚合（借款−偿还，置换归还回填 bank_id）+ 超额借款拦截 + 银行列表额度/已用/剩余列；`test_capital_service` passed |

**回归基线**：backend pytest **575 passed**（原 517 + 新增 58）；前端 `pnpm build` ✓；全量 e2e 单 spec 全绿（我改动的 3 个 spec：s1-advance-error / capital-pools / reconciliation-center 均绿）；全量并跑存在仓库既有的共享库顺序 flake（同批 5 个 spec 单跑 20/20 通过，与本次改动无关）。


## 采购交付线

### D1-01（P0）附件上传失败无反馈
- **判定**：部分属实（"无法上传"不成立，后端/代理正常；失败静默真实存在）
- **证据**：`frontend/src/components/GenericCrud.vue:595-598`（n-upload 只有 `@finish` 无 `@error`，`show-file-list=false` 无进度）；`frontend/src/views/InvoicesView.vue:226-234`（OCR 上传同病）；验收附件 `AcceptanceForm.vue:74-78`、设备导入 `DevicesView.vue:353-367` 有错误提示
- **根因**：上传控件缺失失败回调与 loading 态；失败时界面零反馈
- **修法**：两处 n-upload 补 `@error` 回调（message.error 展示后端 detail）+ 上传中禁用按钮/进度提示
- **测试**：无固化；补前端 e2e 断言（上传 400 时出现错误提示）

### D1-02（P2）设备导入无 EXCEL 模版
- **判定**：属实
- **证据**：`DevicesView.vue:566-585` 导入弹窗无模版下载；后端 `device_service.py:45` `IMPORT_COLS = [sn, leasing_mode, monthly_price, purchase_value, prepayment_amount, ownership]`；`excel_service.py:13-21` 导出清单无设备；仓库无模版文件
- **根因**：导入能力实现一半，模版/字段说明未交付
- **修法**：新增 `GET /excel/devices-template` 生成 xlsx（列头+示例行+说明 sheet）；前端导入弹窗加"下载模版"按钮
- **测试**：补 excel 模版生成单测

### D1-03（P2）设备清单列表行间距不合理
- **判定**：部分属实（一致性漏写，非样式 bug）
- **证据**：`DevicesView.vue:470-479` n-dataTable 未传 `size`（默认 medium 行高 ~40px），全站其余列表均 `size="small"`（~34px）；`class=device-list-table` 无样式定义
- **修法**：表格加 `size="small"`（一行）
- **测试**：无需

### D1-04（P0）设备推进验收失败且报错不解释
- **判定**：属实
- **证据**：状态机 `device_service.py:33-40`（未开始→进行中→已完成/不合格，禁跳步）、`:457-459` 抛 `ILLEGAL_TRANSITION`；硬门1 在途需采购验收通过（`:421-437`）；点亮返工 D5 守门（`:396-418`）；前端 `DevicesView.vue:281` `catch {}` **吞掉具体错误**，`:283` 只报"可能状态机不允许该转换"
- **根因**：后端错误消息其实很明确，前端丢弃了；且推进弹窗不做合法状态预筛、不提示前置
- **修法**：① 前端 `catch` 改为展示 `errMsg(e)`（后端消息如"该设备所属采购订单尚未通过采购验收"）；② 推进弹窗按所选节点状态预筛合法目标状态；③ 批量推进失败时列出失败设备的 SN 与原因；④ 弹窗内提示当前设备前置缺失项
- **测试**：`test_device.py:313-322/452-463`、`test_return.py:78-80` 固化后端行为（保留）；补 e2e 断言失败时前端展示具体错误

---

## 资金线

### D2-01（P0）验收管理与设备清单不关联、验收日期无法录入
- **判定**：属实
- **证据**：`AcceptanceRecord`（`models/acceptance.py:15-28`）无 device 字段，仅销售验收经 `sales_order_id→SalesBatchDevice` 间接关联；创建接口**显式剔除日期** `endpoints/acceptances.py:18` `exclude={'acceptance_date','rejection_reason'}`；服务层写死 `acceptance_service.py:65` `date.today()`；approve 端点不传日期（`:159-162` 缺省 today）；前端 `AcceptanceForm.vue:109-111` 有日期控件但提交被丢弃
- **根因**：schema 留了字段但服务层未实现；验收按订单维度建模无设备勾稽
- **修法**：① 后端 `create_acceptance` 接收 `acceptance_date`、端点不再 exclude；② approve 端点可选传 `acceptance_date`；③ 新增 `PATCH /acceptances/{id}`（编辑验收人/日期/数量）；④ 前端新建验收表单加"验收日期"；⑤ 验收列表/表单展示该订单（批次）下的设备清单（SN/状态）做只读勾稽，数量校验提示
- **测试**：`test_acceptance_service.py:67-72` 仅固化 approve 传日期（保留）；新增 create 传日期生效用例

### D2-02（P0）预付款台账来源错误、无登记时间
- **判定**：属实
- **证据**：台账 `prepayment_service.py:79-96` 纯聚合 `Device.prepayment_amount > 0`，不查 `capital_transactions`；`/capital/prepayment`（`capital_service.py:288-310`）只写两条资金流水、从不回写设备字段；`models/device.py:31/34/36` 无日期列；系统自设"预付款双轨勾稽"页（`ReconciliationCenterView` 第8块）承认两套口径
- **根因**：D2 裁定"设备字段为单一真源"与资金流水模型无同步钩子；设备字段只有金额没有时间
- **修法**（收敛两套账）：① 设备模型加 `prepayment_date`；② 新建 `prepayments` 台账表（supplier_id / contract_id / payment_date / amount / settled_amount / device_id 分摊），`/capital/prepayment` 落表+写流水，设备登记预付款自动落表；③ 台账页改读新表并显示日期/供应商/合同；④ 双轨勾稽页改为断言"表 vs 流水自动一致"（不一致标红）
- **测试**：`test_prepayment.py:110-123` 固化旧聚合口径 → **需更新**；`test_capital_service.py:150-173` 保留

### D2-03（P1）付款管控平台记录收入确认审批
- **判定**：部分属实（后端分流正确，前端漏过滤）
- **证据**：后端 `approval_service.py:83-95` `_cascade` 按 biz_type 正确分派；前端 `PaymentView.vue:23` `api.get('/approvals')` 不带 `biz_type`，把收入确认审批拉进付款页审批中心（`:147-167`）；全前端唯一审批 UI 在付款页
- **修法**：审批中心按 biz_type 分组 Tab（付款申请/收入确认/全部）；`RevenueRecognitionView` 增加行内审批按钮（通过/驳回）
- **测试**：`test_approval.py:23-40`、`test_revenue_recognition.py:82-135` 保留

### D2-04（P1）自有资金池无初始余额拦预付
- **判定**：属实（"先入金后预付"的时序约束，但无引导）
- **证据**：`capital_service.py:296` `_assert_pool_sufficient`，报错文案 `:100-104`；OWN 无期初机制（grep "期初" 仅命中注释 `:232`）；只能手工"记一笔"入金或工作流步骤；新项目 OWN=0，`CapitalView.vue:192` 选自有池预付必被拦
- **修法**：① 资金页加"期初建账"快捷入口（记一笔 自有资金 IN，标注"期初"）；② 余额不足报错文案改为引导语："自有池余额为 0，请先在资金页记一笔期初入金/银行借款"；③ 前端池操作弹窗余额不足时给出可点击跳转
- **测试**：`test_capital_service.py:150-173`、`test_bank_loan_and_repay:145-147` 保留

### D2-05（P1）预付款申请无供应商、无采购合同
- **判定**：属实
- **证据**：`PaymentRequest`（`models/payment.py:35-48`）、`PaymentRequestIn`（`schemas/payment.py:9-16`）、`PrepaymentCreate`（`schemas/capital.py:89-97`）均无 supplier_id；contract_id 两处可选且前端两个入口（`PaymentView.vue:207-214`、`CapitalView.vue:90-96`）都未暴露
- **修法**：① schema/模型加 `supplier_id`（预付必填、付款申请必填）；② 前端预付表单加"供应商+采购合同"下拉；③ 付款申请表单加"供应商+合同"；④ 台账/流水展示供应商名
- **测试**：新增校验用例

---

## 金租流程

### D3-01（P2）金租申请无法修改/作废
- **判定**：属实
- **证据**：`endpoints/leasing.py` 仅 7 端点，无 process 级 PUT/PATCH/DELETE；`schemas/leasing.py` 无 Update/Void；前端 `LeasingView.vue` 详情抽屉只有节点操作/放款/确认还款
- **修法**：① 新增 `PATCH /leasing/processes/{id}`（仅"进行中"未放款可改：金额/利率/期数/频率/方式）；② 新增作废：`POST /leasing/processes/{id}/void`（仅未放款，置状态"已作废"，节点冻结）；③ 前端详情抽屉加"编辑/作废"按钮
- **测试**：新增用例

### D3-02（P2）还款计划自动生成、不可按资金计划调整
- **判定**：部分属实（"不能按季度"不成立，计划不可调成立）
- **证据**：`repayment_plan.py:9` `FREQS_PER_YEAR={"月":12,"季":4,"半年":2}`，schema `PaymentFreq` 与前端下拉均含季（`LeasingView.vue:368`），默认确为"月"；`repayments.py` 只有 GET+PATCH 确认实际值，**不能改 planned_\***
- **修法**：① `PATCH /repayments/{id}` 放开 `planned_principal/planned_interest/due_date` 编辑（校验：本金合计不得超放款额，超则拦截并提示）；② 前端还款计划行加"调整"入口（放款后仍可改计划）；③ 文档说明季度口径
- **测试**：`test_leasing_service.py:46/86` 保留；新增计划调整校验用例

### D3-03（P1）金租放款默认入池记流水（非直付供应商）
- **判定**：属实
- **证据**：`leasing_service.py:116-121`（及 `:194-199`）放款流水 `direction="IN"`、`pool="LEASING"`、`category="放款"`，全程无付供应商 OUT 流水；模型=资金先入赛意金租池再付款
- **修法**（设计评审项）：放款单据加 `mode`（入池/直付）。**入池**=现状；**直付**=金租代付供应商：不生成 LEASING IN 现金流水，生成"金租融资负债入账（IN 挂账）+ 供应商付款 OUT"两笔，还款计划照常。需与财务确认负债记账口径后再实现；本阶段至少：① 字段与 UI 加 mode 选择；② 直付模式实现按上述语义；③ 文档写明两种模式差异
- **测试**：`test_leasing_service.py:74-79`、`test_capital_service.py:200-213`、`test_hard_gates.py:194` 固化入池行为（保留入池用例）；新增直付用例

### D3-04（P1）放款自动冲销、归还日期写死放款日
- **判定**：部分属实（对象是流贷/自有垫资的"置换归还"，非预付款红冲；但"写死放款日"成立）
- **证据**：`leasing_service.py:124-134/201-204` 自动调 `fs.execute_replacement`；`funding_service.py:50-62` 生成 IN"置换归还"流水、`transaction_date=disbursement_date`（无时间参数）；对象仅 `source_type in [银行流贷, 自有资金]`，**不含预付**；预付退回是手动端点
- **修法**：① `execute_replacement` 加 `replacement_date` 参数（默认放款日，可传实际归还日）；② 放款弹窗加"置换归还日"（默认放款日可改）；③ 置换记录展示归还日；④ 文档/UI 说明"自动置换的是流贷/自有垫资，预付款退回需手动操作"
- **测试**：`test_funding_service.py:38-77` 固化引擎行为（保留，扩展日期参数用例）

---

## 销售线

### D4-01（P1）计费管理挂在采购订单上
- **判定**：部分属实（订单维计费 UI 挂采购订单；销售订单未接入）
- **证据**：`billings.py:25-37` order_id → `orders`（采购订单表）；金额取销售合同 `monthly_rent`（`billing_service.py:48-52`）；销售订单仅按台计费经 `device.sales_contract_id` 反查回填（`:109-120`）；前端 `BillingsView.vue:56-58` 生成计费下拉是 `/orders`
- **修法**：① 计费页"按订单生成"改选销售订单（`/sales-orders`）；② `POST /billings` 支持 `sales_order_id`（新接口 `POST /billings/sales-order`：批内设备汇总出一张计费单，或逐台生成并挂 sales_order_id）；③ 计费列表"订单"列显示销售订单号
- **测试**：`test_w5_6_billing.py:199-215`、`test_billing_invoice_service.py:150-158` 保留 legacy；新增销售订单维用例

### D4-02（P1）只能按台计费、不能按订单/批次
- **判定**：部分属实
- **证据**：两入口都在（`POST /billings` + `POST /billings/device`），但设备粒度订单被防双计闸 `assert_legacy_path` 409 `FLOW_TYPE_DEVICE`（`billing_service.py:43-44`、`device_service.py:685-695`）；全库无"按销售订单/批次整体出单"接口
- **修法**：随 D4-01 实现 `POST /billings/sales-order`（按销售订单汇总出单，单台金额仍按 device.monthly_price 计算）；前端"生成计费"两个入口并存并标明适用场景
- **测试**：新增用例

### D4-03（P0）按台计费走不通（未点亮不能计费）
- **判定**：属实
- **证据**：`_device_light_on_date`（`billing_service.py:96-106`）要求 `DeviceStage(点亮验收, 已完成, actual_date 非空)`；点亮被状态机禁跳步 + 硬门1（在途需采购验收）卡住；前端吞错误（见 D1-04）
- **修法**：随 D1-04 修报错可读化；计费页生成前展示前置状态检查（设备当前节点/是否点亮）；无法计费时给出明确原因与下一步
- **测试**：`test_device.py:313-316/325-337/340-358`、`test_hard_gates.py:71-85`、`test_w5_6_billing.py:99-109` 保留

### D4-04（P0）客户确认/对账链路断
- **判定**：部分属实（确认单强依赖计费不可测；对账/对账单是只读聚合，页面可进只是没数据）
- **证据**：`confirmation` 的 `billing_id` 必填（`schemas/confirmation.py:8-9`、`models/service_confirmation.py:15`）；`ConfirmationForm.vue:48-50` 只列有计费的单；开票被硬门4锁在已确认对账单之后（`invoice_service.py:15-35`）
- **修法**：随 D4-01 打通计费；确认单页面给出"当前无可确认计费单"时提示去计费；开票被拦时报错升级为"请先在客户确认单页生成并确认对账单"并附跳转
- **测试**：`test_hard_gates.py:124-172` 保留

### D4-05（P1）对账单是累计口径，非当期费用
- **判定**：属实
- **证据**：`report_service.py:161-222` 聚合无 period 过滤（合同额/累计计费/开票/回款）；对账动作=确认/争议（`confirmations.py:34-52`），无"对平"动作；对账中心纯只读
- **修法**：① `customer-statement` 接口加 `period`（YYYY-MM）参数，按当期计费/开票/回款过滤；② 对账单页加"当期/累计"切换；③ 增加"对平"展示：当期应收 vs 当期回款差异
- **测试**：`test_customer_statement.py:47-66` 固化累计断言（保留）；新增当期口径用例

---

## 财务核算

### D5-01（P2）发票 OCR 不可用
- **判定**：部分属实（链路完整，部署/分支缺陷）
- **证据**：`ocr_service.py:12-18` 依赖本机 tesseract + `chi_sim` 语言包（仅 Dockerfile 装）；PDF 分支**代码级必败**（`PIL.Image.open` 不支持 PDF，而接口与前端 `accept="image/*,.pdf"` 都允许）；`ocr.py:24-27` 把异常吞成 HTTP 200 + error 字段
- **修法**：① 前端 accept 去掉 `.pdf` 并提示"仅支持图片"（或后端用 pdf2image 支持 PDF，需 poppler，作为可选增强）；② 后端异常改为 4xx/5xx 或保持 200+error 但前端明确展示；③ 后端启动自检：tesseract/语言包缺失时 health 端点报告 ocr 不可用，前端按钮提示"OCR 服务不可用"
- **测试**：无 OCR 测试；新增 OCR 服务单测（mock tesseract）

### D5-02（P2）发票"到期日必填"（实为空串提交）
- **判定**：部分属实（字段全链路非必填；前端空串 `''` 提交被 Pydantic 日期校验拦下——已实测 Pydantic 2.13.3 复现）
- **证据**：`schemas/invoice.py:13` 可选、`models/billing.py:59` nullable、`schema.sql:346` 无 NOT NULL；前端 `InvoicesView.vue:251` 有"到期日"控件且 `form.due_date=''` 初始值原样提交 → 422
- **修法**：① 前端移除"到期日"输入框（业务无此概念，来自 v1 设计的应付预警字段）；② 双保险：后端给 `InvoiceCreate` 加 validator 把空串转 None；③ 迁移可选删除 due_date 列（保守：保留列但不再展示）
- **测试**：新增空串兼容用例

### D5-03（P0）开票被"无已确认客户对账单"拦截
- **判定**：属实
- **证据**：`invoice_service.py:15-35` `_assert_statement_confirmed`（仅 RECEIVABLE + 有销售订单的合同生效；无销售订单放行）；`test_hard_gates.py` 门4 三用例固化
- **修法**：门保留（业务合理），但：① 报错信息带上下文（"该合同已有销售订单，需先生成并确认客户对账单"）；② 前端发票页被拦时提示跳转确认单页；③ 确认单页在无可确认计费时给出明确指引（随 D4-04）
- **测试**：`test_hard_gates.py:124-172` 保留

### D5-04（P1）收入确认"无法自动生成"
- **判定**：部分属实（触发源已改为开票驱动，计费钩子下线；链条卡死导致开票不了则收入确认确实出不来）
- **证据**：`invoice_service.py:65-67` 开票即调 `generate_draft_for_invoice`；`generate_draft_for_billing`（`revenue_recognition_service.py:26-57`）存在但未接线；`models/revenue.py:27` 注释"不再按计费"
- **修法**：不改触发源（避免双确认），改为：① 收入确认页 UI 明确"开票即自动生成确认草稿"；② 随 D4-01 打通计费→确认→开票链；③ 保证开票成功即出草稿的路径在 e2e 覆盖
- **测试**：`test_revenue_recognition.py` 全量按开票驱动（保留）

---

## 主数据

### D6-01（P1）供应商/客户字段不足（缺开票信息/银行账号）
- **判定**：属实
- **证据**：`models/master.py:13-18` 供应商仅 `bank_account` 自由文本；`:27-32` 客户无银行/开票字段；`SupplierOut`（`schemas/master.py:20-28`）连 bank_account 都不返回；全库 grep 税号/抬头/开户行零命中
- **修法**：① 供应商加 `tax_no/invoice_title/bank_name/bank_account/address`（结构化）；② 客户加 `bank_name/bank_account/invoice_title/tax_no`；③ schema 输出补全；④ 前端表单对应加字段
- **测试**：`test_master_service.py:41-48` 保留；新增字段集断言

### D6-02（P1）银行授信无使用/余额
- **判定**：属实
- **证据**：`models/master.py:50-58` 银行仅 `credit_line/annual_rate`；`record_bank_loan`（`capital_service.py:257-269`）只写流水不回写 Bank；`credit_line` 全库无"已用/剩余"计算
- **修法**：① 查询层计算：已用授信 = 该银行借款流水 ΣIN − Σ归还（按 bank_id 聚合）；② 银行列表/详情显示 额度/已用/剩余；③ `/capital/bank-loan` 校验剩余额度（超额拦截）；④ 前端银行表单不变，列表加列
- **测试**：`test_bank_loan_and_repay`（池余额语义）保留；新增授信聚合用例

---

## 附：修复时需同步更新的测试（锁定旧行为）

| 测试 | 锁定行为 | 处置 |
|---|---|---|
| `test_prepayment.py:110-123` | 台账按设备聚合且无日期 | **更新**为读新台账表（含日期/供应商/合同） |
| `test_hard_gates.py:124-172` | 门4 开票前置 | 保留（行为不变，只改报错文案） |
| `test_revenue_recognition.py` | 开票驱动收入确认 | 保留 |
| `test_leasing_service.py:74-86` | 放款入池 + 季频到期日 | 保留入池用例；新增直付用例 |
| `test_funding_service.py:38-77` | 置换引擎 | 保留；扩展日期参数 |
| `test_customer_statement.py:47-66` | 累计口径 | 保留；新增当期用例 |
| `test_master_service.py` | 银行利率 CHECK | 保留（勿破坏 `test_bank_rate_check`） |
| `test_bank_loan_and_repay` | 银行池余额语义 | 保留 |

**全局约束**：每阶段完成后跑 `pytest`（backend）、`pnpm build`（frontend）、关键路径 e2e，不得带红上线。
