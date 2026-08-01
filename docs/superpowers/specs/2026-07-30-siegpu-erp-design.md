# SIEGPU 算力租赁 ERP 系统设计

> 日期：2026-07-30 | 状态：DRAFT v1.0（已审计，已被 v2.0 取代） | 作者：赛意信息 财务总监需求
>
> 📌 **最新版本**：[v2.0 详细设计](./2026-07-30-siegpu-erp-design-v2.md) ｜ **v1.0 审计报告**：[AUDIT-2026-07-30-siegpu-erp-design-v1.md](./AUDIT-2026-07-30-siegpu-erp-design-v1.md)

---

## 1. 项目概述

### 1.1 背景

赛意信息（300687）进入算力租赁领域，以"下游签租 + 上游采购 + 金融租赁融资"模式运营。当前用 Excel 管理，痛点在于：

- 资金池头寸看不清——多项目共用资金池，不知道某时点还要准备多少钱
- 金租审批进度失控——不知道项目卡在金租哪个环节，没人主动推进
- 合同发票对账乱——收付两端发票匹配不上，财务月结花大量时间

### 1.2 目标

构建一个小型 ERP 系统，覆盖算力租赁业务**从合同签订到设备折旧退役**的全生命周期，核心解决资金池、金租流程、发票对账三大痛点。

### 1.3 用户

| 角色 | 人数 | 核心模块 |
|---|---|---|
| 财务总监 | 1 | 全量读写 |
| 采购对接人 | 1 | 主数据 / 合同 / 订货到点亮 |
| 项目交付负责人 | 1 | 金租流程 / 订货到点亮 / 还款跟踪 |
| 财务专员 | 1 | 资金池 / 计费发票 / 还款 / 资产 |

3-5 人内网使用，Web 应用浏览器访问。

### 1.4 业务核心流程

```
签约（销售合同 + 采购合同，一对多级联）
  → 资金筹措（自有 20-30% + 银行流贷 70-80%）
    → 金租审批（接触→交流→资料提交→审核→一次上会→二次上会→访谈→批方案，1-2 月）
      → 金租放款（还流贷 + 付尾款）
        → 订货交付（订货→到货→压测→运输在途→共同上架→点亮验收）
          → 运营（计费/收发票/付发票/对账/还款/折旧）
```

滚动订货：多个批次可同时处于不同阶段，各批次独立跟踪。

---

## 2. 技术架构

### 2.1 选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | **Python 3.12+ FastAPI** | 团队有 Python 能力；FastAPI 轻量、自动 OpenAPI 文档、异步支持 |
| ORM | **SQLAlchemy 2.0 + Alembic** | 成熟稳定，迁移管理 |
| 数据库 | **PostgreSQL 16** | 关系型、JSON 支持、窗口函数（资金池汇总必备） |
| 前端 | **Vue 3 Composition API + Naive UI** | Vue 上手快，Naive UI 组件丰富适合企业后台 |
| 部署 | **Docker Compose**（PostgreSQL + FastAPI + Vue/Nginx） | 一条命令启动，内网一台服务器即可 |
| 认证 | **JWT（OAuth2 Password Flow）** | 简单够用，3-5 人无需复杂 SSO |

### 2.2 部署拓扑

```
内网服务器（Docker Compose）
├── PostgreSQL:5432      — 数据持久化（volume 挂载）
├── FastAPI:8000          — 后端 REST API
├── Vue/Nginx:8080        — 前端 SPA + 反向代理 /api → FastAPI
```

---

## 3. 数据模型

### 3.1 实体关系总览

```
customers ──→ projects ←── banks
                   │
     ┌─────────────┼──────────────┐
     ↓             ↓              ↓
 contracts     leasing_       capital_
 (级联)       processes    transactions
     │             │              │
     ↓             ↓              ↓
  orders      leasing_      capital_
     │          nodes       allocations
     ↓             │
 delivery_     repayments
  stages           │
     │          invoices ←── contracts
     ↓
  assets
```

### 3.2 表清单（13 张）

#### 主数据域

**suppliers** — 供应商主数据
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(200) | 供应商名称 |
| type | VARCHAR(20) | 设备供应商 / 资金供应商 / 其他 |
| contact_person | VARCHAR(100) | 联系人 |
| contact_phone | VARCHAR(50) | 联系电话 |
| bank_account | TEXT | 银行账户信息 |
| notes | TEXT | 备注 |
| created_at / updated_at | TIMESTAMP | 时间戳 |

> 金租公司 `type='资金供应商'`，作为主数据统一管理。

**customers** — 下游客户
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(200) | 客户名称 |
| industry | VARCHAR(100) | 行业 |
| contact_person | VARCHAR(100) | 联系人 |
| contact_phone | VARCHAR(50) | 联系电话 |
| credit_rating | VARCHAR(20) | 信用评级 |
| notes | TEXT | 备注 |

**equipment_models** — 设备型号目录
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(200) | 型号名称 |
| category | VARCHAR(20) | 大卡 / 小卡 / 组网设备 |
| gpu_type | VARCHAR(100) | GPU 类型 |
| gpu_count | INTEGER | 单台 GPU 数量 |
| memory | VARCHAR(50) | 显存规格 |
| spec_json | JSONB | 其他规格参数 |
| unit_price_reference | DECIMAL(15,2) | 参考单价 |

**banks** — 银行
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(200) | 银行名称 |
| contact_person | VARCHAR(100) | 联系人 |
| credit_line | DECIMAL(15,2) | 授信总额度 |
| interest_rate | DECIMAL(5,4) | 流贷年利率 |
| notes | TEXT | 备注 |

#### 项目与合同域

**projects** — 项目
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(200) | 如"商机5090" |
| code | VARCHAR(50) | 项目编号 |
| customer_id | UUID | FK → customers |
| status | VARCHAR(20) | 进行中 / 已完成 / 暂停 |
| total_investment | DECIMAL(15,2) | 总投资额 |
| start_date | DATE | 项目开始日期 |
| notes | TEXT | 备注 |

**contracts** — 合同
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects |
| contract_no | VARCHAR(100) | 合同编号 |
| type | VARCHAR(10) | 销售合同 / 采购合同 |
| party_id | UUID | FK → suppliers 或 customers（多态） |
| party_type | VARCHAR(20) | supplier / customer |
| amount | DECIMAL(15,2) | 合同金额 |
| start_date | DATE | 合同开始 |
| end_date | DATE | 合同结束 |
| parent_contract_id | UUID | 自引用 FK，采购子合同级联 |
| status | VARCHAR(20) | 草稿 / 已签 / 执行中 / 已完成 |
| file_path | VARCHAR(500) | 合同文件路径 |

> 级联：一个项目下可以有多个采购合同（大卡/小卡/组网），`parent_contract_id` 表示父子关系。

#### 资金域（一期核心）

**capital_transactions** — 资金流水（统一账本）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects |
| source_type | VARCHAR(20) | 自有资金 / 银行流贷 / 金租融资 / 租金收入 |
| direction | VARCHAR(4) | IN / OUT |
| amount | DECIMAL(15,2) | 金额 |
| transaction_date | DATE | 发生日期 |
| bank_id | UUID | FK → banks，流贷相关 |
| contract_id | UUID | FK → contracts，关联合同 |
| leasing_process_id | UUID | FK → leasing_processes |
| category | VARCHAR(50) | 订金 / 尾款 / 还本 / 付息 / 租金 / 调配 / 其他 |
| note | TEXT | 摘要 |
| created_by | UUID | 录入人 |

**capital_allocations** — 跨项目调配
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| from_project_id | UUID | FK → projects |
| to_project_id | UUID | FK → projects |
| amount | DECIMAL(15,2) | 调配金额 |
| allocation_date | DATE | 调配日期 |
| expected_return_date | DATE | 预计归还日期 |
| actual_return_date | DATE | 实际归还日期 |
| reason | TEXT | 调配原因 |
| status | VARCHAR(20) | 已调配 / 已归还 / 逾期 |
| approved_by | UUID | 审批人 |

#### 金租流程域（一期核心）

**leasing_processes** — 金租申请
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects |
| supplier_id | UUID | FK → suppliers（type=资金供应商） |
| total_amount | DECIMAL(15,2) | 申请融资总额 |
| status | VARCHAR(20) | 进行中 / 已批 / 已放款 / 已拒绝 |
| start_date | DATE | 接触日期 |
| approval_date | DATE | 批准日期 |
| disbursement_date | DATE | 实际放款日期 |
| notes | TEXT | 备注 |

**leasing_nodes** — 流程节点（每个申请 9 个节点）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| process_id | UUID | FK → leasing_processes |
| node_name | VARCHAR(50) | 节点名称 |
| seq | INTEGER | 排序号 1-9 |
| status | VARCHAR(20) | 未开始 / 进行中 / 已完成 / 卡住 |
| planned_date | DATE | 计划完成日期 |
| actual_date | DATE | 实际完成日期 |
| owner_id | UUID | 负责人 |
| notes | TEXT | 备注 |
| attachments | JSONB | 附件路径数组 |

> 九个标准节点（按序）：1.接触 → 2.业务交流 → 3.资料提交 → 4.金租审核 → 5.一次上会 → 6.二次上会 → 7.访谈 → 8.批方案 → 9.放款

#### 交付与运营域

**orders** — 采购订单
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects |
| contract_id | UUID | FK → contracts |
| equipment_model_id | UUID | FK → equipment_models |
| quantity | INTEGER | 数量 |
| unit_price | DECIMAL(15,2) | 单价 |
| total_amount | DECIMAL(15,2) | 总金额 |
| order_date | DATE | 下单日期 |
| expected_delivery_date | DATE | 预计到货 |
| status | VARCHAR(20) | 已下单 / 部分到货 / 已到货 |

**delivery_stages** — 交付阶段跟踪
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| order_id | UUID | FK → orders |
| stage | VARCHAR(20) | 订货 / 到货 / 压测 / 运输在途 / 上架 / 点亮 |
| seq | INTEGER | 排序 1-6 |
| status | VARCHAR(20) | 未开始 / 进行中 / 已完成 |
| planned_date | DATE | 计划日期 |
| actual_date | DATE | 实际日期 |
| notes | TEXT | 备注 |

**invoices** — 发票（一期核心）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| contract_id | UUID | FK → contracts |
| direction | VARCHAR(4) | 收 / 付 |
| invoice_no | VARCHAR(100) | 发票号码 |
| amount | DECIMAL(15,2) | 发票金额 |
| tax_amount | DECIMAL(15,2) | 税额 |
| issue_date | DATE | 开票日期 |
| due_date | DATE | 到期日 |
| paid_date | DATE | 实际付款日 |
| status | VARCHAR(20) | 未开 / 已开 / 已收票 / 已付款 |
| file_path | VARCHAR(500) | 发票扫描件 |
| matched_contract_id | UUID | 对账匹配的对方合同 |

**repayments** — 还款记录
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| leasing_process_id | UUID | FK → leasing_processes |
| period | INTEGER | 期数（1-20 = 5年×4季） |
| due_date | DATE | 到期日 |
| planned_principal | DECIMAL(15,2) | 计划还本 |
| planned_interest | DECIMAL(15,2) | 计划付息 |
| actual_principal | DECIMAL(15,2) | 实际还本 |
| actual_interest | DECIMAL(15,2) | 实际付息 |
| paid_date | DATE | 实际付款日 |
| status | VARCHAR(20) | 待还 / 已还 / 逾期 |

**assets** — 固定资产
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects |
| equipment_model_id | UUID | FK → equipment_models |
| quantity | INTEGER | 数量 |
| unit_original_value | DECIMAL(15,2) | 单台原值 |
| total_original_value | DECIMAL(15,2) | 总原值（= 数量 × 单台原值） |
| residual_rate | DECIMAL(4,3) | 残值率，固定 0.10 |
| residual_value | DECIMAL(15,2) | 残值（= 总原值 × 10%） |
| depreciable_value | DECIMAL(15,2) | 应折旧额（= 总原值 − 残值） |
| annual_depreciation | DECIMAL(15,2) | 年折旧额（= 应折旧额 ÷ 5） |
| start_date | DATE | 折旧开始日期（点亮日） |
| end_date | DATE | 折旧结束日期 |
| status | VARCHAR(20) | 折旧中 / 已提完 |

### 3.3 资金池核心查询逻辑

```sql
-- 资金池总余额
SELECT
  SUM(CASE WHEN direction='IN' THEN amount ELSE -amount END) AS balance
FROM capital_transactions;

-- 按来源类型拆分明细
SELECT
  source_type,
  SUM(CASE WHEN direction='IN' THEN amount ELSE 0 END) AS total_in,
  SUM(CASE WHEN direction='OUT' THEN amount ELSE 0 END) AS total_out,
  SUM(CASE WHEN direction='IN' THEN amount ELSE -amount END) AS net
FROM capital_transactions
GROUP BY source_type;

-- 各项目资金占用（出金 − 入金）
SELECT
  p.name AS project_name,
  SUM(CASE WHEN ct.direction='OUT' THEN ct.amount ELSE 0 END) -
  SUM(CASE WHEN ct.direction='IN' THEN ct.amount ELSE 0 END) AS net_occupancy
FROM projects p
LEFT JOIN capital_transactions ct ON ct.project_id = p.id
GROUP BY p.id, p.name;
```

### 3.4 发票对账核心查询

```sql
-- 按合同汇总：合同金额 vs 已收/付发票
SELECT
  c.id, c.contract_no, c.type, c.amount AS contract_amount,
  COALESCE(SUM(i.amount), 0) AS invoiced_amount,
  c.amount - COALESCE(SUM(i.amount), 0) AS gap
FROM contracts c
LEFT JOIN invoices i ON i.contract_id = c.id
GROUP BY c.id, c.contract_no, c.type, c.amount
HAVING c.amount - COALESCE(SUM(i.amount), 0) != 0;  -- 仅显示有差异的
```

---

## 4. 模块详细设计

### 4.1 主数据管理

**功能**：供应商（含金租）、客户、设备型号、银行的增删改查。

**要点**：
- 供应商列表可按 type 筛选（设备/资金/其他）
- 设备型号支持 category（大卡/小卡/组网）
- 银行记录含授信额度和利率

**页面**：4 个 Tab 页（供应商 / 客户 / 设备型号 / 银行），每个是标准 CRUD 表格。

### 4.2 合同管理

**功能**：销售合同和采购合同的录入、查看、级联管理。

**要点**：
- 合同绑定项目
- 采购合同支持 `parent_contract_id` 做父子级联
- 合同状态：草稿 → 已签 → 执行中 → 已完成
- 支持上传合同扫描件

**页面**：
- 合同列表（可按项目/类型/状态筛选）
- 合同详情（含子合同树形展示）
- 新建/编辑合同表单

### 4.3 资金池管理（一期核心）

**功能**：管理所有资金流入流出，实时查看资金池状态。

**核心交互**：
- 记一笔：录入 capital_transaction（入金 or 出金、来源类型、关联项目/合同）
- 跨项目调配：从 A 项目调到 B 项目，生成两条 transaction（一出/一入）+ 一条 allocation 记录
- 仪表盘：实时余额、按来源拆分、各项目占用、最近流水

**仪表盘组件**：
1. 4 个指标卡片：池总余额 / 流贷余额 / 金租已批未放 / 未来30天应付
2. 各项目资金占用表（自有/流贷/金租/合计）
3. 最近 10 笔流水
4. 预警列表

**预警规则**：
| 预警 | 触发条件 | 级别 |
|---|---|---|
| 资金池余额不足 | 余额 < 未来30天应付总额 | 🔴 高危 |
| 流贷即将到期 | 距离还本日 < 15天 | 🟠 警告 |
| 金租放款延迟 | 预计放款日已过未到账 | 🔴 高危 |
| 调配未归还 | 预计归还日已过 | 🟠 警告 |

### 4.4 金租流程跟踪（一期核心）

**功能**：管理金租申请全流程，从接触跟踪到放款。

**核心交互**：
- 新建申请：选项目 + 选金租公司 + 填融资额 → 自动生成 9 个节点
- 节点推进：点击节点，更新状态 + 记录实际完成日期
- 节点卡住标记：`status='卡住'` + 填写原因
- 附件上传：每个节点可上传对应资料文件
- 放款确认：第 9 节点完成 → 自动提示是否生成 capital_transaction 入金记录

**页面**：
- 金租申请列表（按项目/状态筛选）
- 申请详情（9 个节点的进度条/时间线）
- 节点编辑弹窗

**进度可视化**：横向时间线，不同颜色标识（灰=未开始、蓝=进行中、绿=已完成、红=卡住）。

### 4.5 订货到点亮

**功能**：采购订单和交付进度的批次跟踪。

**核心交互**：
- 新建订单：选项目/合同/设备型号 → 自动生成 6 个交付阶段
- 交付推进：每个订单独立跟踪 6 个阶段
- 点亮确认：标记点亮日期 → 触发计费起点

**页面**：
- 订单列表（按项目/状态筛选）
- 订单详情（6 阶段进度 + 设备信息）
- 阶段编辑弹窗

### 4.6 计费与发票（一期核心）

**功能**：收付两端发票管理和对账。

**核心交互**：
- 收发票登记：关联销售合同，记录发票号/金额/开票日/收款日
- 付发票登记：关联采购合同，记录发票号/金额/收票日/付款日
- 对账视图：合同金额 vs 已开票金额 vs 差异，标红有差异的

**页面**：
- 发票列表（可按方向/状态筛选）
- 对账仪表盘（差异一览表）
- 新建/编辑发票弹窗

**计费逻辑**：点亮验收日 = 计费起点，按比例（当月剩余天数/当月总天数）计算首月，之后按固定月租。

### 4.7 还款跟踪

**功能**：管理金租还款的计划与实际对比。

**核心交互**：
- 手动录入还款计划（20 期，每期还本 + 付息）
- 逐期确认实际还款
- 逾期标记（到期未还标红）

**页面**：
- 还款计划表（20 行，计划 vs 实际对比，差异标红）
- 汇总行：总本金 / 总利息 / 已还 / 未还

### 4.8 资产管理

**功能**：固定资产登记与折旧计算。

**核心交互**：
- 点亮后自动/手动生成资产记录
- 系统自动计算：残值 = 原值 × 10%，年折旧 =（原值 − 残值）÷ 5
- 按年查看折旧进度

**页面**：
- 资产列表
- 资产折旧明细表

### 4.9 仪表盘（首页）

**功能**：登录后首页，一览全局。

**组件**：
- 资金池 4 个核心指标卡片
- 金租进度总览（各项目当前节点 + 卡住高亮）
- 待办提醒（逾期还款 / 到期流贷 / 发票差异 / 调配未归还）
- 项目交付进度概览

---

## 5. API 设计概述

RESTful API，FastAPI 自动生成 `/docs`。

### 5.1 主要端点

```
GET    /api/projects              # 项目列表
POST   /api/projects              # 新建项目
GET    /api/projects/{id}         # 项目详情

GET    /api/contracts?project_id= # 合同列表
POST   /api/contracts             # 新建合同

GET    /api/capital/transactions  # 资金流水
POST   /api/capital/transactions  # 记一笔
GET    /api/capital/summary       # 资金池汇总（仪表盘用）
POST   /api/capital/allocate      # 跨项目调配

GET    /api/leasing/processes     # 金租申请列表
POST   /api/leasing/processes     # 新建申请
GET    /api/leasing/processes/{id}/nodes  # 节点列表
PATCH  /api/leasing/nodes/{id}    # 更新节点状态

GET    /api/orders                # 订单列表
POST   /api/orders                # 新建订单
GET    /api/orders/{id}/stages    # 交付阶段
PATCH  /api/delivery-stages/{id}  # 更新阶段

GET    /api/invoices              # 发票列表
POST   /api/invoices              # 录入发票
GET    /api/invoices/reconciliation  # 对账视图

GET    /api/repayments            # 还款列表
POST   /api/repayments            # 录入还款计划
PATCH  /api/repayments/{id}       # 确认还款

GET    /api/assets                # 资产列表
GET    /api/dashboard/alerts      # 仪表盘预警
```

### 5.2 认证与用户管理

JWT Bearer Token，登录接口 `/api/auth/login` 返回 token，前端存 localStorage，每次请求带 `Authorization: Bearer <token>`。

用户账号由管理员（财务总监）在系统中创建，不开放自助注册。4 个角色（财务总监/采购对接人/项目交付负责人/财务专员）对应 4 个权限组，后端中间件按角色校验 API 权限。

### 5.3 关键业务逻辑补充

**未来 30 天应付总额计算**：汇总以下来源在接下来 30 天内的应付金额：

- `repayments` 表中 `due_date` 在未来 30 天内且 `status='待还'` 的 `planned_principal + planned_interest`
- `invoices` 表中 `due_date` 在未来 30 天内且 `direction='付'` 且 `status != '已付款'` 的 `amount`

**跨项目调配审批**：调配操作由财务专员发起 → 财务总监审批 → 系统自动生成两条 capital_transaction（一出一入）+ 一条 capital_allocation。`approved_by` 记录审批人。

---

## 6. 前端页面结构

```
/login                          # 登录页
/                               # 首页仪表盘
/projects                       # 项目列表
/projects/:id                   # 项目详情（含合同/资金/金租/交付子 Tab）
/contracts                      # 合同列表
/capital                        # 资金池仪表盘
/capital/transactions           # 资金流水明细
/leasing                        # 金租申请列表
/leasing/:id                    # 金租申请详情（时间线）
/orders                         # 采购订单列表
/orders/:id                     # 订单详情（交付进度）
/invoices                       # 发票列表 + 对账
/repayments                     # 还款管理
/assets                         # 资产管理
/master-data                    # 主数据管理（供应商/客户/设备/银行 Tab）
```

---

## 7. 开发路线图

### 一期（MVP，约 4-6 周）

| 周 | 内容 |
|---|---|
| 1-2 | 项目骨架（Docker + FastAPI + Vue 脚手架）、主数据 CRUD、用户认证 |
| 2-3 | 项目管理 + 合同管理（含级联） |
| 3-4 | **资金池管理**（含仪表盘、调配、预警）|
| 4-5 | **金租流程跟踪**（含时间线、节点管理） |
| 5-6 | **计费发票**（含对账视图）、部署上线 |

### 二期（后续迭代）

- 自动化利润测算（复用现有 Excel 模型逻辑）
- Excel 导入/导出
- 通知提醒（邮件/企业微信）
- 操作日志/审计

---

## 8. 与现有 Excel 资产的关系

| Excel 文件 | 在新系统中的处理 |
|---|---|
| 采购明细 | → orders 表 + contracts 表 |
| 合同要素清单 | → 合同录入时的字段模板 |
| 庭宇测算（现金流） | → capital_transactions + repayments |
| 庭宇测算（利润表） | → 二期利润测算功能 |
| 财务报表 | → 二期报表模块 |

一期手工初始化数据：逐条录入主数据和历史记录，不搞批量导入。

---

## 9. 非功能性要求

- 数据安全：PostgreSQL 每日自动备份（pg_dump）
- 权限：JWT + 角色中间件，4 个角色各有独立的读写权限
- 性能：3-5 人使用，无并发压力，单服务器即可
- 浏览器兼容：现代浏览器（Chrome/Edge/Firefox 最近 2 个版本）

---

## 10. 风险与假设

| 风险 | 缓解 |
|---|---|
| 业务需求变化快 | 模块化设计，各模块独立可改 |
| 金租审批流程可能因不同金租公司而异 | leasing_nodes 可动态增删节点，不硬编码 |
| 团队 Python/前端经验不足 | 选型最简（FastAPI + Vue），避免过度工程化 |
| 数据初始化工作量大 | 一期只上线当前活跃项目，历史数据留在 Excel 中按需查阅 |

---

## 附录 A：数据库 SQL（DDL 骨架）

```sql
-- 仅展示核心表结构，完整 DDL 由 Alembic 迁移管理

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    code VARCHAR(50) UNIQUE,
    customer_id UUID REFERENCES customers(id),
    status VARCHAR(20) DEFAULT '进行中',
    total_investment DECIMAL(15,2),
    start_date DATE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE capital_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    source_type VARCHAR(20) NOT NULL,    -- 自有资金/银行流贷/金租融资/租金收入
    direction VARCHAR(4) NOT NULL,        -- IN/OUT
    amount DECIMAL(15,2) NOT NULL,
    transaction_date DATE NOT NULL,
    bank_id UUID REFERENCES banks(id),
    contract_id UUID REFERENCES contracts(id),
    leasing_process_id UUID REFERENCES leasing_processes(id),
    category VARCHAR(50),
    note TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_ct_project ON capital_transactions(project_id);
CREATE INDEX idx_ct_date ON capital_transactions(transaction_date);
CREATE INDEX idx_ct_source ON capital_transactions(source_type);

CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id UUID REFERENCES contracts(id),
    direction VARCHAR(4) NOT NULL,
    invoice_no VARCHAR(100),
    amount DECIMAL(15,2) NOT NULL,
    tax_amount DECIMAL(15,2) DEFAULT 0,
    issue_date DATE,
    due_date DATE,
    paid_date DATE,
    status VARCHAR(20) DEFAULT '未开',
    file_path VARCHAR(500),
    matched_contract_id UUID REFERENCES contracts(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_inv_contract ON invoices(contract_id);
CREATE INDEX idx_inv_direction ON invoices(direction);
```

---

> **文档版本**：v1.0 | **最后更新**：2026-07-30
