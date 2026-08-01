# SIEGPU 算力租赁 ERP 系统设计 v2.0（详细设计）

> 日期：2026-07-30 | 状态：DRAFT v2.0（含复审修订 NF1–NF6 + NW1–NW17） | 基于 [v1.0](./2026-07-30-siegpu-erp-design.md) 审计迭代 + 独立复审
> 审计报告：[AUDIT-2026-07-30-siegpu-erp-design-v1.md](./AUDIT-2026-07-30-siegpu-erp-design-v1.md)（FAIL 6 / WARNING 24，已逐条消化）
> 上一版：v1.0（已被取代，保留作演进对比）

---

## 0. v1.0 → v2.0 变更摘要

| # | 变更 | 对应审计项 | 章节 |
|---|---|---|---|
| 1 | 新增 `billings` 计费/收入确认表，分离"应收 / 开票 / 收款"三流 | F1, W14 | §3.2, §5.3 |
| 2 | 新增 `users` 表，补齐 `created_by / approved_by / owner_id` 悬空外键 | F2 | §3.2 |
| 3 | 新增 `audit_logs` 表 + 操作留痕，**从二期前移至一期** | F5, W22 | §3.2, §9.4, §10 |
| 4 | 新增"幂等与事务策略"：`idempotency_keys` 表 + `Idempotency-Key` 头 + 动作唯一约束 + DB 事务 | F3 | §3.6, §6.1 |
| 5 | 新增"软删除 + 红冲"机制：全表 `deleted_at`，财务表禁止硬改金额，纠错走反向冲销凭证 | F4, W7 | §3.7 |
| 6 | 新增"测试策略"章节：pytest 单元 + 集成 + Playwright E2E，80% 覆盖率，每模块 DoD | F6 | §8 |
| 7 | 状态机显式化：9 张表的合法迁移表 + 后端强制校验 | W11 | §3.5 |
| 8 | `direction` 统一为 `IN/OUT`（资金流）/ `RECEIVABLE/PAYABLE`（票据），全链路一致 | W8 | §1.6, §3.2 |
| 9 | 全表统一 `created_at + updated_at`（触发器自动维护）+ `deleted_at` | W9 | §3.4 |
| 10 | 单位约定：所有 `rate` 字段存**小数**（如 0.0435），附全链路对照表 | W10 | §1.6, 附录 B |
| 11 | 发票 ↔ 资金流水建立外键 `capital_transaction_id`，付款自动回填 | W12 | §3.2, §5.6 |
| 12 | `leasing_processes` 增 `annual_rate / term_periods / payment_freq / repayment_method / actual_disbursement_amount`；放款自动生成还款计划 | W13, W19, W6 | §3.2, §5.5 |
| 13 | 折旧改为月折旧直线法，首末月按实际天数，`end_date = 点亮日 + 5 年` | W15 | §5.4 |
| 14 | 调配前置校验"可调余额"；发票超开拦截；金租申请额 vs 实付额对账 | W17, W18, W19 | §5.1, §5.6, §5.8 |
| 15 | 点亮 → 资产生成 → 折旧起点，在同一 DB 事务内完成 | W20 | §3.6, §5.4 |
| 16 | 放款日期以 `leasing_processes.disbursement_date` 为单一真相源 | W21 | §3.2, §5.5 |
| 17 | 一期路线图显式纳入：RBAC 中间件、审计日志、测试、历史数据初始化 | F5, W22, W24 | §10 |
| 18 | Excel → 表映射按磁盘真实文件重写（含 7加7 / 商机5090 测算） | W23 | §12 |
| 19 | 表数量由"13 张"更正为 **19 张** | W16 | §3.2 |

---

## 1. 项目概述

### 1.1 背景

赛意信息（300687）进入算力租赁领域，以"下游签租 + 上游采购 + 金融租赁融资"模式运营。当前用 Excel 管理，痛点：

- **资金池头寸看不清**——多项目共用资金池，不知道某时点还要准备多少钱
- **金租审批进度失控**——不知道项目卡在金租哪个环节，没人主动推进
- **合同发票对账乱**——收付两端发票匹配不上，财务月结花大量时间

### 1.2 目标

构建小型 ERP，覆盖算力租赁业务**从合同签订到设备折旧退役**全生命周期，核心解决资金池、金租流程、发票对账三大痛点。

### 1.3 用户与角色职责

| 角色（role 枚举） | 人数 | 核心职责 | 主要模块 |
|---|---|---|---|
| 财务总监 `FINANCE_DIRECTOR` | 1 | 全局读写、审批调配/超开、管用户、看审计 | 全模块 + 用户管理 + 审计日志 |
| 采购对接人 `PROCUREMENT` | 1 | 主数据、采购合同、订货到点亮 | 主数据 / 合同（采购）/ 订单 / 交付 |
| 项目交付负责人 `DELIVERY` | 1 | 金租流程推进、交付点亮、还款跟踪 | 金租 / 订单 / 交付 / 还款（读） |
| 财务专员 `FINANCE_STAFF` | 1 | 资金池、计费发票、还款、资产 | 资金池 / 计费 / 发票 / 还款 / 资产 |

3-5 人内网使用，Web 应用浏览器访问。账号由财务总监在系统内创建，不开放自助注册。

> `ADMIN` 角色（NW6）：系统初始引导账号，等价 `FINANCE_DIRECTOR` 全权 + 用户管理 + 系统设置；日常业务用上述 4 角色，`ADMIN` 仅用于初始化与应急。

### 1.4 业务核心流程与"三流"

```
签约（销售合同 + 采购合同，一对多级联）
  → 资金筹措（自有 20-30% + 银行流贷 70-80%）
    → 金租审批（9 节点，1-2 月）
      → 金租放款（还流贷 + 付尾款，自动生成还款计划）
        → 订货交付（订货→到货→压测→运输在途→上架→点亮）
          → 运营（计费/开票/收付/对账/还款/折旧）
```

v2.0 显式区分**三条数据流**，三者独立但相互勾稽（对账之本）：

| 流 | 实体 | 含义 | 发生时点 |
|---|---|---|---|
| **物流/服务流** | `delivery_stages` → `billings` | 设备交付、点亮、按月确认应收收入 | 点亮后按月 |
| **票据流** | `invoices` | 开票（销售收票）/ 收票（采购付票），税务口径 | 按开票行为 |
| **资金流** | `capital_transactions` | 实际现金收付 | 实际收付款日 |

> v1.0 只有票据流（invoices）和资金流（capital_transactions），**漏了物流对应的应收/收入流**，导致月结和利润测算拿不到权责发生制数字。v2.0 用 `billings` 补齐。

### 1.5 术语表

| 术语 | 含义 |
|---|---|
| 点亮 | 设备上电验收通过，计费与折旧的共同起点 |
| 金租 | 金融租赁公司，作为"资金供应商"在 `suppliers` 中管理 |
| 流贷 | 银行流动资金贷款，过渡性融资，金租放款后偿还 |
| 调配 | 跨项目临时划转资金归属，不改变资金池总余额（一出一入净 0） |
| 红冲 | 财务纠错方式：不删除不改原记录，新建一条等额反向记录冲销 |
| 计费起点 | 点亮日，首月按剩余天数比例计租 |
| 可调余额 | 项目净资金头寸中可被调出的部分 = max(0, 净头寸 − 已冻结) |

### 1.6 单位与量纲约定（全项目硬约定）

> 对应审计 W10/W14。所有开发人员/前后端必须遵守此约定，杜绝"百分数 vs 小数""含税 vs 不含税"混用。

| 字段类别 | 约定 | 示例 |
|---|---|---|
| 金额 | `DECIMAL(18,2)`，单位**元**，**不含税**（除 `invoices`/`billings` 显式标注含税字段外） | 1,000,000.00 |
| 利率 / 残值率 / 税率 | `NUMERIC(10,8)`，存**小数**（非百分数）；DDL 强制 `CHECK (rate BETWEEN 0 AND 1)` 防百分数直填（NW5） | 年利率 4.35% → `0.04350000`；残值率 10% → `0.10000000`；增值税 13% → `0.13000000` |
| `direction`（资金流） | 枚举 `IN` / `OUT` | 收款 `IN`、付款 `OUT` |
| `direction`（票据/应收） | 枚举 `RECEIVABLE`（销售，我方收票）/ `PAYABLE`（采购，我方付票） | 销售合同对应 `RECEIVABLE` |
| 含税口径 | `invoices` / `billings` 同时存 `amount`（含税）、`amount_ex_tax`（不含税）、`tax_amount`（税额）、`tax_rate`，关系 `amount = amount_ex_tax + tax_amount`；`contracts.monthly_rent` 亦为**含税**月租（计费用，NW8 补入例外） | — |
| 日期 | `DATE`（业务日）/ `TIMESTAMPTZ`（系统时间，存 UTC） | — |

全链路对照表见 [附录 B](#附录-b单位与量纲全链路对照表)。

---

## 2. 技术架构

### 2.1 选型

| 层 | 选型（版本） | 理由 |
|---|---|---|
| 后端 | Python 3.12 + FastAPI 0.115+ | 团队有 Python 能力；自动 OpenAPI；async |
| ORM | SQLAlchemy 2.0 + Alembic 1.13+ | 成熟，迁移管理 |
| DB | PostgreSQL 16 | 关系型 + JSONB + 窗口函数 + ENUM + 触发器（updated_at 自动维护） |
| 前端 | Vue 3.4+（Composition API）+ Naive UI 2.38+ + Pinia + Vite | 上手快，企业后台组件全 |
| 部署 | Docker Compose | 一条命令，内网单机 |
| 认证 | JWT（OAuth2 Password Flow），access 30min + refresh 7d | 简单够用 |
| 测试 | pytest + httpx（API）+ Playwright（E2E） | 见 §8 |

### 2.2 部署拓扑

```
内网服务器（Docker Compose）
├── db: PostgreSQL:5432        — volume pgdata，每日 pg_dump
├── backend: FastAPI:8000      — uvicorn，挂载 /app/uploads
├── frontend: Nginx:8080       — SPA 静态 + 反向代理 /api → backend
└── （可选）watchtower / pgadmin
```

网络：Compose 内网 `siegpu_net`；仅 Nginx 8080 对内网暴露；DB 不对外。

### 2.3 后端目录结构

```
backend/
├── app/
│   ├── main.py                      # FastAPI 实例、中间件、路由挂载
│   ├── core/
│   │   ├── config.py                # pydantic-settings 读 .env
│   │   ├── db.py                    # engine, Session, Base
│   │   ├── security.py              # JWT, 密码 hash(passlib[bcrypt])
│   │   ├── deps.py                  # get_db / get_current_user / require_role
│   │   ├── idempotency.py           # Idempotency-Key 中间件 + 记录读写
│   │   ├── audit.py                 # 审计日志切面（SQLAlchemy event listener）
│   │   └── exceptions.py            # 统一业务异常 + 错误码
│   ├── models/                      # SQLAlchemy ORM，按域分文件
│   │   ├── base.py                  # TimestampMixin, SoftDeleteMixin
│   │   ├── user.py  audit.py  master.py  project.py  capital.py
│   │   ├── leasing.py  delivery.py  billing.py  invoice.py  repayment.py  asset.py
│   ├── schemas/                     # Pydantic v2，请求/响应
│   ├── api/v1/endpoints/            # 路由，薄层，只做参数校验+调 service
│   ├── services/                    # 业务逻辑：事务边界、状态机校验、副作用编排
│   │   ├── capital_service.py  leasing_service.py  delivery_service.py
│   │   ├── billing_service.py  invoice_service.py  repayment_service.py  asset_service.py
│   ├── repos/                       # 纯数据访问（可选，小项目可并入 service）
│   └── utils/                       # 计算：depreciation.py, repayment_plan.py, billing.py
│   └── tests/                       # unit/ + integration/
├── alembic/versions/
├── uploads/                         # 合同/发票/附件扫描件（volume）
├── requirements.txt
├── Dockerfile
└── .env.example
```

### 2.4 前端目录结构

```
frontend/src/
├── main.ts  App.vue
├── router/                  # 路由 + 守卫（按 role 控制可访问路由）
├── stores/                  # Pinia: auth / capital / leasing / invoice ...
├── api/                     # axios 实例（拦截器：注入 token、401 跳登录、错误统一提示）
│   ├── client.ts  capital.ts  leasing.ts  invoice.ts ...
├── views/                   # 与 §6 路由一一对应
├── components/              # 通用组件：StateTimeline / AmountInput / ReconcileTable
├── composables/             # useFormRules / useIdempotentSubmit
├── types/                   # 与后端 schema 对齐的 TS 类型
└── utils/                   # format.ts（金额/日期格式化）
```

### 2.5 配置与密钥管理

- `.env`（gitignore，不入库）：`DATABASE_URL`、`JWT_SECRET`、`UPLOAD_DIR`、`BACKUP_DIR`、`VAT_DEFAULT=0.13`、`IDEMPOTENCY_TTL_HOURS=24`。
- `.env.example` 入库作模板。
- 生产密钥（JWT_SECRET）由财务总监注入，不写进镜像；Docker Compose 用 `env_file`。

### 2.6 横切关注点（统一实现位置）

| 关注点 | 实现位置 | 说明 |
|---|---|---|
| 事务边界 | `services/*` | 每个业务动作一个事务，多表写入原子提交 |
| 幂等 | `core/idempotency.py` + `idempotency_keys` 表 | 见 §3.6 |
| 审计日志 | `core/audit.py`（SQLAlchemy `before_flush` 监听） | 自动捕获 CREATE/UPDATE/DELETE，见 §3.7/§9.4 |
| 软删除 | `models/base.py` SoftDeleteMixin + 查询默认 `deleted_at IS NULL` | 见 §3.7 |
| 状态机校验 | `services/*` 内 `assert_transition(old, new)` | 见 §3.5 |
| 统一异常 | `core/exceptions.py` → HTTP 错误码 | 见 §6.2 |

---

## 3. 数据模型

### 3.1 实体关系图（v2.0）

```
users ──→ audit_logs（记录所有写操作）
  │ created_by/approved_by/owner_id 渗透各表
  │
customers ──→ projects ←── banks
                   │
     ┌─────────────┼──────────────┐
     ↓             ↓              ↓
 contracts     leasing_       capital_
 (级联)       processes      transactions ←─ idempotency_keys
     │             │              │
     ↓             ↓              ↓
  orders      leasing_       capital_
     │          nodes       allocations
     ↓
 delivery_        │
  stages      repayments
     │             │
     ↓          invoices ←── billings（应收→开票→收款三流勾稽）
  assets           ↑
（点亮生成）   contracts
```

### 3.2 表清单（19 张）

> 通用列（除 `audit_logs`/`idempotency_keys` 外所有表都有）：`id UUID PK`、`created_at TIMESTAMPTZ`、`updated_at TIMESTAMPTZ`、`deleted_at TIMESTAMPTZ NULL`。下表只列业务字段。

#### 基础设施域（3 张，v2.0 新增）

**users** — 用户 *（F2）*
| 字段 | 类型 | 说明 |
|---|---|---|
| username | VARCHAR(50) UNIQUE | 登录名 |
| display_name | VARCHAR(100) | 显示名 |
| password_hash | VARCHAR(255) | bcrypt |
| role | VARCHAR(20) | CHECK in (FINANCE_DIRECTOR, PROCUREMENT, DELIVERY, FINANCE_STAFF, ADMIN) |
| active | BOOLEAN DEFAULT TRUE | 启用/停用 |
| last_login_at | TIMESTAMPTZ | 最近登录 |

**audit_logs** — 操作审计 *（F5，一期）*
| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | UUID FK→users | 操作人 |
| action | VARCHAR(20) | CREATE/UPDATE/DELETE/REVERSE/LOGIN |
| entity_type | VARCHAR(50) | 表名 |
| entity_id | UUID | 记录 id |
| before_json | JSONB | 改前快照 |
| after_json | JSONB | 改后快照 |
| request_id | VARCHAR(64) | 请求/幂等键 |
| ip | VARCHAR(45) | 来源 IP |
| at | TIMESTAMPTZ | 时间（append-only，禁 update/delete） |

> 仅插入、不更新、不软删；按月分区或按年归档。

**idempotency_keys** — 幂等记录 *（F3）*
| 字段 | 类型 | 说明 |
|---|---|---|
| key | VARCHAR(128) PK | 客户端传入的 Idempotency-Key |
| user_id | UUID FK→users | |
| endpoint | VARCHAR(100) | |
| request_hash | VARCHAR(64) | 请求体 hash（防同 key 不同体） |
| response_status | SMALLINT | 首次响应码 |
| response_body | JSONB | 首次响应体 |
| created_at | TIMESTAMPTZ | TTL 24h，定时清理 |

#### 主数据域（4 张）

**suppliers** — 供应商（含金租公司）
| 字段 | 类型 | 说明 |
|---|---|---|
| name | VARCHAR(200) | |
| type | VARCHAR(20) | CHECK in (设备供应商, 资金供应商, 其他)；金租公司=资金供应商 |
| contact_person / contact_phone | VARCHAR | |
| bank_account | TEXT | |
| notes | TEXT | |

**customers** — 下游客户
| 字段 | 类型 | 说明 |
|---|---|---|
| name | VARCHAR(200) | |
| industry | VARCHAR(100) | |
| contact_person / contact_phone | VARCHAR | |
| credit_rating | VARCHAR(20) | |

**equipment_models** — 设备型号
| 字段 | 类型 | 说明 |
|---|---|---|
| name | VARCHAR(200) | |
| category | VARCHAR(20) | CHECK in (大卡, 小卡, 组网设备) |
| gpu_type | VARCHAR(100) | |
| gpu_count | INTEGER | 单台 GPU 数 |
| memory | VARCHAR(50) | 显存 |
| spec_json | JSONB | 其他规格 |
| unit_price_reference | DECIMAL(18,2) | 参考单价（不含税） |

**banks** — 银行
| 字段 | 类型 | 说明 |
|---|---|---|
| name | VARCHAR(200) | |
| contact_person / contact_phone | VARCHAR | |
| credit_line | DECIMAL(18,2) | 授信总额度 |
| annual_rate | NUMERIC(10,8) | 流贷年利率（小数，0.0435） |

#### 项目与合同域（2 张）

**projects** — 项目
| 字段 | 类型 | 说明 |
|---|---|---|
| name | VARCHAR(200) | 如"商机5090" |
| code | VARCHAR(50) UNIQUE | |
| customer_id | UUID FK→customers | |
| status | VARCHAR(20) | CHECK in (进行中, 暂停, 已完成, 已终止) |
| total_investment | DECIMAL(18,2) | 总投资额 |
| start_date | DATE | |

**contracts** — 合同
| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| contract_no | VARCHAR(100) | |
| type | VARCHAR(20) | CHECK in (SALES, PURCHASE)（销售/采购） |
| party_type | VARCHAR(20) | supplier / customer |
| party_id | UUID | 多态 FK（应用层校验） |
| direction | VARCHAR(12) | CHECK in (RECEIVABLE, PAYABLE)；SALES→RECEIVABLE，PURCHASE→PAYABLE |
| amount | DECIMAL(18,2) | 合同总额（不含税） |
| tax_rate | NUMERIC(10,8) | 合同税率（默认 0.13） |
| monthly_rent | DECIMAL(18,2) | 月租（销售合同，含税）；计费用 |
| start_date / end_date | DATE | |
| parent_contract_id | UUID FK→contracts | 自引用，采购子合同级联 |
| status | VARCHAR(20) | CHECK in (草稿, 已签, 执行中, 已完成, 已终止) |
| file_path | VARCHAR(500) | 扫描件 |

#### 资金域（2 张，一期核心）

**capital_transactions** — 资金流水（统一账本）*（统一 direction=IN/OUT）*
| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| source_type | VARCHAR(20) | CHECK in (自有资金, 银行流贷, 金租融资, 租金收入, 调配, 调配归还, 还款) |
| direction | VARCHAR(4) | CHECK in (IN, OUT) |
| amount | DECIMAL(18,2) | |
| transaction_date | DATE | |
| bank_id | UUID FK→banks | 流贷相关 |
| contract_id | UUID FK→contracts | |
| leasing_process_id | UUID FK→leasing_processes | |
| invoice_id | UUID FK→invoices | 收付款关联发票 *（W12 新增）* |
| category | VARCHAR(50) | 订金/尾款/还本/付息/租金/调配/其他 |
| idempotency_key | VARCHAR(128) | 动作去重 *（F3 新增）* |
| reversal_of_id | UUID FK→capital_transactions | 红冲反向凭证指向原记录 *（F4 新增）* |
| note | TEXT | |
| created_by | UUID FK→users | |

> 约束：`idempotency_key` 部分唯一索引（WHERE idempotency_key IS NOT NULL）；`reversal_of_id` 形成原-冲配对；金额纠错只能新增反向记录，禁止 UPDATE amount。

**capital_allocations** — 跨项目调配
| 字段 | 类型 | 说明 |
|---|---|---|
| from_project_id / to_project_id | UUID FK→projects | |
| amount | DECIMAL(18,2) | |
| allocation_date | DATE | |
| expected_return_date | DATE | |
| actual_return_date | DATE | |
| reason | TEXT | |
| status | VARCHAR(20) | CHECK in (已调配, 已归还, 逾期) |
| approved_by | UUID FK→users | 审批人 |
| out_txn_id / in_txn_id | UUID FK→capital_transactions | 配套两条流水 *（F3 新增，便于回溯）* |

**idempotency_keys** — 见基础设施域。

#### 金租流程域（2 张，一期核心）

**leasing_processes** — 金租申请 *（W13/W19/W21 新增利率期数字段）*
| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| supplier_id | UUID FK→suppliers | type=资金供应商 |
| total_amount | DECIMAL(18,2) | 申请融资总额 |
| actual_disbursement_amount | DECIMAL(18,2) | 实际放款额 *（W19 新增，与申请额对账）* |
| annual_rate | NUMERIC(10,8) | 金租年利率（小数） *（W13 新增）* |
| term_periods | SMALLINT | 期数（如 20） *（W13 新增）* |
| payment_freq | VARCHAR(12) | CHECK in (月, 季, 半年)；默认季 *（W6/W13 新增）* |
| repayment_method | VARCHAR(12) | CHECK in (等额本息, 等额本金) *（W13 新增）* |
| status | VARCHAR(20) | CHECK in (进行中, 已批, 已放款, 已拒绝) |
| start_date | DATE | 接触日 |
| approval_date | DATE | 批准日 |
| disbursement_date | DATE | **实际放款日（单一真相源）** *（W21）* |
| plan_generated | BOOLEAN DEFAULT FALSE | 还款计划是否已生成 *（F3 幂等）* |

**leasing_nodes** — 流程节点（每申请 N 节点，默认 9，可动态增删）
| 字段 | 类型 | 说明 |
|---|---|---|
| process_id | UUID FK→leasing_processes | |
| node_name | VARCHAR(50) | |
| seq | INTEGER | 排序 |
| status | VARCHAR(20) | CHECK in (未开始, 进行中, 已完成, 卡住) |
| planned_date / actual_date | DATE | |
| owner_id | UUID FK→users | 负责人 |
| attachments | JSONB | 附件路径数组 |
| stuck_reason | TEXT | 卡住原因 |

> 9 标准节点：1.接触 → 2.业务交流 → 3.资料提交 → 4.金租审核 → 5.一次上会 → 6.二次上会 → 7.访谈 → 8.批方案 → 9.放款。节点模板可按金租公司覆盖。

#### 交付与运营域（6 张）

**orders** — 采购订单
| 字段 | 类型 | 说明 |
|---|---|---|
| project_id / contract_id | UUID FK | |
| equipment_model_id | UUID FK→equipment_models | |
| quantity | INTEGER | |
| unit_price | DECIMAL(18,2) | 不含税 |
| total_amount | DECIMAL(18,2) | = quantity × unit_price |
| order_date / expected_delivery_date | DATE | |
| status | VARCHAR(20) | CHECK in (已下单, 部分到货, 已到货, 已点亮) |

**delivery_stages** — 交付阶段（每订单 6 阶段）
| 字段 | 类型 | 说明 |
|---|---|---|
| order_id | UUID FK→orders | |
| stage | VARCHAR(20) | CHECK in (订货, 到货, 压测, 运输在途, 上架, 点亮) |
| seq | INTEGER | 1-6 |
| status | VARCHAR(20) | CHECK in (未开始, 进行中, 已完成) |
| planned_date / actual_date | DATE | |

**billings** — 计费/收入确认 *（F1 新增，一期核心）*
| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | UUID FK→projects | |
| contract_id | UUID FK→contracts | 销售合同（RECEIVABLE） |
| order_id | UUID FK→orders | 来源订单 |
| period_index | INTEGER | 第几期（点亮后第 N 月） |
| period_label | VARCHAR(20) | 如"2026-10" |
| billing_date | DATE | 收入确认日（默认期末） |
| days_in_period | INTEGER | 本期计费天数（首月按比例） |
| amount | DECIMAL(18,2) | 应收含税 |
| amount_ex_tax | DECIMAL(18,2) | 不含税收入 |
| tax_amount | DECIMAL(18,2) | 税额 |
| tax_rate | NUMERIC(10,8) | |
| status | VARCHAR(20) | CHECK in (未开, 已开, 已收款, 已红冲) |
| invoice_id | UUID FK→invoices | 开票后回填 |
| capital_transaction_id | UUID FK→capital_transactions | 收款后回填 |
| idempotency_key | VARCHAR(128) | 计费生成去重 |
| reversal_of_id | UUID FK→billings | 红冲反向凭证 *（NW4 新增）* |

> 三流勾稽：`billings`（应收）→ 开票回填 `invoice_id` → 收款回填 `capital_transaction_id`。对账据此自动完成（§5.6）。

**invoices** — 发票 *（W12/W14 新增字段，direction 统一 RECEIVABLE/PAYABLE）*
| 字段 | 类型 | 说明 |
|---|---|---|
| contract_id | UUID FK→contracts | |
| direction | VARCHAR(12) | CHECK in (RECEIVABLE, PAYABLE) |
| invoice_no | VARCHAR(100) | |
| amount | DECIMAL(18,2) | 含税金额 |
| amount_ex_tax | DECIMAL(18,2) | 不含税 *（W14 新增）* |
| tax_amount | DECIMAL(18,2) | 税额 |
| tax_rate | NUMERIC(10,8) | *（W14 新增）* |
| issue_date / due_date / paid_date | DATE | |
| status | VARCHAR(20) | CHECK in (待开, 已开, 已收票, 已付款, 已红冲) |
| capital_transaction_id | UUID FK→capital_transactions | 收付款流水 *（W12 新增）* |
| reversal_of_id | UUID FK→invoices | 红冲反向凭证 *（NW4 新增）* |
| file_path | VARCHAR(500) | 扫描件 |

**repayments** — 还款记录 *（W6：period 不再硬编码 1-20）*
| 字段 | 类型 | 说明 |
|---|---|---|
| leasing_process_id | UUID FK→leasing_processes | |
| period | INTEGER | 期数（由 term_periods 决定，非写死 20） |
| due_date | DATE | |
| planned_principal / planned_interest | DECIMAL(18,2) | |
| actual_principal / actual_interest | DECIMAL(18,2) | |
| paid_date | DATE | |
| capital_transaction_id | UUID FK→capital_transactions | 还款流水 *（W12 新增）* |
| reversal_of_id | UUID FK→repayments | 红冲反向凭证 *（NW4 新增）* |
| status | VARCHAR(20) | CHECK in (待还, 已还, 逾期) |

**assets** — 固定资产 *（W15：折旧月化）*
| 字段 | 类型 | 说明 |
|---|---|---|
| project_id / equipment_model_id | UUID FK | |
| order_id | UUID FK→orders | 来源 *（与订单勾稽）* |
| quantity | INTEGER | |
| unit_original_value / total_original_value | DECIMAL(18,2) | |
| residual_rate | NUMERIC(10,8) | 固定 0.10 |
| residual_value / depreciable_value | DECIMAL(18,2) | |
| annual_depreciation | DECIMAL(18,2) | = 应折旧额 / 5 |
| monthly_depreciation | DECIMAL(18,2) | = 年 / 12 *（W15 新增）* |
| start_date | DATE | 点亮日（点亮同事务写入） |
| end_date | DATE | = 点亮日 + 5 年 *（W15 公式化）* |
| status | VARCHAR(20) | CHECK in (折旧中, 已提完) |

### 3.3 完整 DDL（核心表）

> 限于篇幅展示关键与新增表的 DDL；其余表按 §3.2 字段 + 通用列 `id/created_at/updated_at/deleted_at` 同构。完整 DDL 由 Alembic 迁移管理。

```sql
-- 通用：updated_at 自动维护
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- 通用：软删除查询视图（示例，应用层也可在 ORM 加默认 filter）
-- 所有业务表查询都带 WHERE deleted_at IS NULL

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('FINANCE_DIRECTOR','PROCUREMENT','DELIVERY','FINANCE_STAFF','ADMIN')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,                -- append-only，不用 UUID 也行
    user_id UUID REFERENCES users(id),
    action VARCHAR(20) NOT NULL CHECK (action IN ('CREATE','UPDATE','DELETE','REVERSE','LOGIN','APPROVE_OVERCONTRACT','SUPERSEDE')),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID,
    before_json JSONB,
    after_json JSONB,
    request_id VARCHAR(64),
    ip VARCHAR(45),
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_user_time ON audit_logs(user_id, at);
-- 注意：audit_logs 上不建 updated_at/deleted_at；应用 DB role 仅授 INSERT/SELECT，REVOKE UPDATE,DELETE,TRUNCATE（NW15，防 ORM 误改/误删）

CREATE TABLE idempotency_keys (
    key VARCHAR(128) PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    endpoint VARCHAR(100) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    response_status SMALLINT,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_idem_created ON idempotency_keys(created_at);

CREATE TABLE capital_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    source_type VARCHAR(20) NOT NULL CHECK (source_type IN ('自有资金','银行流贷','金租融资','租金收入','调配','调配归还','还款')),
    direction VARCHAR(4) NOT NULL CHECK (direction IN ('IN','OUT')),
    amount DECIMAL(18,2) NOT NULL CHECK (amount > 0),
    transaction_date DATE NOT NULL,
    bank_id UUID REFERENCES banks(id),
    contract_id UUID REFERENCES contracts(id),
    leasing_process_id UUID REFERENCES leasing_processes(id),
    invoice_id UUID REFERENCES invoices(id),
    category VARCHAR(50),
    idempotency_key VARCHAR(128),
    reversal_of_id UUID REFERENCES capital_transactions(id),
    is_reversal BOOLEAN NOT NULL DEFAULT FALSE,   -- 本条是否为红冲反向记录（复审 NF2）
    note TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
    -- 红冲方向校验在 service 层：反向记录 direction 必须与原记录相反、金额相等。
    -- PG 的 CHECK 不允许子查询（复审 NF2），故不在 DDL 内做跨行校验。
);
CREATE UNIQUE INDEX uq_ct_idem ON capital_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_ct_project ON capital_transactions(project_id);
CREATE INDEX idx_ct_date ON capital_transactions(transaction_date);
CREATE INDEX idx_ct_source ON capital_transactions(source_type);
CREATE TRIGGER trg_ct_updated BEFORE UPDATE ON capital_transactions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE leasing_processes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    supplier_id UUID REFERENCES suppliers(id),
    total_amount DECIMAL(18,2) NOT NULL,
    actual_disbursement_amount DECIMAL(18,2),
    annual_rate NUMERIC(10,8) CHECK (annual_rate BETWEEN 0 AND 0.99999999),  -- 防 4.35 直填（NW5）
    term_periods SMALLINT,
    payment_freq VARCHAR(12) CHECK (payment_freq IN ('月','季','半年')),
    repayment_method VARCHAR(12) CHECK (repayment_method IN ('等额本息','等额本金')),
    status VARCHAR(20) NOT NULL DEFAULT '进行中'
        CHECK (status IN ('进行中','已批','已放款','已拒绝')),
    start_date DATE,
    approval_date DATE,
    disbursement_date DATE,
    plan_generated BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TRIGGER trg_lp_updated BEFORE UPDATE ON leasing_processes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE billings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    contract_id UUID REFERENCES contracts(id),
    order_id UUID REFERENCES orders(id),
    period_index INTEGER NOT NULL,
    period_label VARCHAR(20) NOT NULL,
    billing_date DATE NOT NULL,
    days_in_period INTEGER NOT NULL,
    amount DECIMAL(18,2) NOT NULL,           -- 含税
    amount_ex_tax DECIMAL(18,2) NOT NULL,
    tax_amount DECIMAL(18,2) NOT NULL,
    tax_rate NUMERIC(10,8) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT '未开'
        CHECK (status IN ('未开','已开','已收款','已红冲')),
    invoice_id UUID REFERENCES invoices(id),
    capital_transaction_id UUID REFERENCES capital_transactions(id),
    idempotency_key VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT chk_billing_tax CHECK (amount = ROUND(amount_ex_tax + tax_amount, 2))
);
CREATE UNIQUE INDEX uq_billing_idem ON billings(idempotency_key) WHERE idempotency_key IS NOT NULL;
-- 计费粒度为"订单 × 期"，唯一键含 order_id（复审 NF6：同合同多订单点亮日不同，不能只按 contract_id+period）
CREATE UNIQUE INDEX uq_billing_period ON billings(order_id, period_index) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_billing_updated BEFORE UPDATE ON billings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

### 3.4 通用字段约定

| 字段 | 类型 | 规则 |
|---|---|---|
| `id` | UUID PK | `gen_random_uuid()` |
| `created_at` | TIMESTAMPTZ | 默认 now()，建记录时写入 |
| `updated_at` | TIMESTAMPTZ | 触发器 `BEFORE UPDATE` 自动置 now() |
| `deleted_at` | TIMESTAMPTZ NULL | 软删除标记；ORM 基类默认 `WHERE deleted_at IS NULL` |
| `created_by` | UUID FK→users | 仅关键财务表（如 `capital_transactions`）必填；其余表"录入人"由 `audit_logs` 追溯（NW11） |

> 对应审计 W9：v1.0 多数财务表无 `updated_at`，v2.0 全表统一并由触发器维护。

### 3.5 状态机（合法迁移表）

> 对应审计 W11。后端 `services/*` 调 `assert_transition` 强制，非法迁移抛 `IllegalTransitionError`（HTTP 409）。

| 表 | 当前态 | 允许迁入 |
|---|---|---|
| projects | 进行中 | 暂停 / 已完成 / 已终止 |
| | 暂停 | 进行中 / 已终止 |
| contracts | 草稿 | 已签 |
| | 已签 | 执行中 / 已终止 |
| | 执行中 | 已完成 / 已终止 |
| leasing_processes | 进行中 | 已批 / 已拒绝 |
| | 已批 | 已放款 |
| leasing_nodes | 未开始 | 进行中 |
| | 进行中 | 已完成 / 卡住 |
| | 卡住 | 进行中 |
| orders | 已下单 | 部分到货 |
| | 部分到货 | 已到货 |
| | 已到货 | 已点亮（触发资产生成） |
| delivery_stages | 未开始 | 进行中 |
| | 进行中 | 已完成（点亮完成触发计费起点+资产生成） |
| invoices | 待开 | 已开 |
| | 已开 | 已收票（RECEIVABLE）/ 已付款（PAYABLE） |
| billings | 未开 | 已开 |
| | 已开 | 已收款 |
| repayments | 待还 | 已还 / 逾期 |
| | 逾期 | 已还 |
| assets | 折旧中 | 已提完 |
| capital_allocations | 已调配 | 已归还 / 逾期 |
| | 逾期 | 已归还 |

> 任一财务表记录可被"红冲"迁入"已红冲"终态（不可逆），见 §3.7。

### 3.6 幂等与事务策略

> 对应审计 F3。三条"动作→自动生成财务记录"链路必须可安全重试。

**两层防护**：

1. **通用幂等层**（`Idempotency-Key` 头 + `idempotency_keys` 表）
   - 客户端对写操作（尤其放款/调配/点亮/计费生成/确认收款）在请求头带 `Idempotency-Key: <uuid>`。
   - 中间件 `core/idempotency.py`：命中同 key → 校验 `request_hash` 一致 → 直接回放 `response_body`；hash 不一致 → 409。
   - TTL 24h，定时任务清理。

2. **业务级去重**（动作唯一约束 / 状态守卫，事务内）
   - 放款：`leasing_processes.plan_generated` + 状态 `已放款` 守卫；`SELECT ... FOR UPDATE` 锁行后再次校验，重复放款抛 409。
   - 调配：两条流水用**不同**键 `allocate:{allocation_id}:OUT` / `allocate:{allocation_id}:IN`（避免撞 `uq_ct_idem` 唯一索引，复审 NF1）；整笔调配的幂等由通用层 `Idempotency-Key` 头 + `capital_allocations` 唯一约束/状态守卫保证。
   - 点亮：`orders.status='已点亮'` 守卫 + `assets.order_id` 唯一约束（一订单一批资产只生成一次）。
   - 计费：`billings(contract_id, period_index)` 唯一约束（同合同同期不重复生成）。

**事务边界**：每个 service 方法一个 DB 事务，多表写入原子提交；任一失败全回滚。

| 链路 | 事务内动作 | 去重键 |
|---|---|---|
| 金租放款 | 设 `disbursement_date`、状态→已放款、写 `capital_transactions`(IN)、生成 `repayments` N 期 | `leasing_process_id` + `plan_generated` |
| 跨项目调配 | 写 `capital_allocations` + 2 条 `capital_transactions`(OUT/IN)，**键按腿区分** | `allocate:{allocation_id}:OUT` / `:IN` |
| 调配归还 | 状态→已归还 + 反向 2 条 `capital_transactions`(IN 回 from / OUT 出 to) | `allocate-return:{allocation_id}:IN` / `:OUT` |
| 点亮确认 | `delivery_stages`→已完成、`orders`→已点亮、创建 `assets`、设 `start_date` | `orders.id` + `assets.order_id` 唯一 |
| 计费生成（按月） | 批量写 `billings` | `(contract_id, period_index)` 唯一 |

### 3.7 软删除与红冲机制

> 对应审计 F4/W7。财务数据**禁止硬删除、禁止直接改金额**。

- **软删除**：业务表删除 = 置 `deleted_at`，查询默认过滤；仅用于录错的非金额主数据（如重复供应商）。
- **红冲纠错**（金额类：`capital_transactions` / `invoices` / `billings` / `repayments`）：
  1. 原记录不可改不可删，状态置"已红冲"。
  2. 新建反向记录：金额等值、`direction` 取反、`reversal_of_id` 指向原记录。
  3. 若需更正，再新建一条正确记录。
  4. 红冲必须填原因（`note`），且需财务总监审批（权限矩阵 §4）。
- **审计**：红冲动作 `action=REVERSE`，`before_json/after_json` 完整留痕。
- **防呆**（NW7）：反向记录不可再被红冲（终态）；若需两次纠错，红冲原反向记录后再新建正确记录。调配的流水被红冲时，同事务把 `capital_allocations.status` 回退（如置"已撤销"），保持 `allocatable` 与 `capital_transactions` 一致。

---

## 4. 权限矩阵（角色 × 模块 × 动作）

> 对应审计 W22。动作：V=查看 C=新增 E=编辑 D=软删 A=审批 X=导出。"·"=无权。

| 模块 | 财务总监 | 采购对接人 | 项目交付 | 财务专员 |
|---|---|---|---|---|
| 主数据（供应商/客户/设备/银行） | VCED | VCE | V | V |
| 项目 | VCED | VCE | VE | V |
| 合同（销售+采购） | VCED | VCE（采购） | V | V |
| 资金流水 | VCE | V | V | VCE |
| 跨项目调配 | VA | · | · | VC（发起，待A） |
| 金租流程 | VCE | V | VCE | V |
| 订单 / 交付 | VCE | VCE | VCE | V |
| 计费（billings） | VCE | V | V | VCE |
| 发票 | VCED+超开A | V | V | VCE（超开需A） |
| 还款 | VCE | V | VE（确认） | VCE |
| 资产 | V | V | V | VCE |
| 仪表盘 / 预警 | V | V | V | V |
| 用户管理 | VCED | · | · | · |
| 审计日志 | V | · | · | · |
| 红冲审批 | A | · | · | · |

实现：`core/deps.py` 提供 `require_role(*roles)` 依赖；路由级 + service 级双重校验（service 内对审批类动作再校验角色）。

---

## 5. 业务算法

### 5.1 资金池模型与可调余额

**定义**（对应审计 W17，澄清 v1.0"共享池 vs 子池"）：

- **单一共享池**：资金池总余额 = Σ `capital_transactions`（IN − OUT），跨所有项目、不分项目。调配一出一入，对总余额净影响为 0，仅改变项目间归属。
- **项目净头寸**：`net_position(p) = ΣIN(p) − ΣOUT(p)`。正值=项目净注入（有可调余额），负值=项目净占用（消耗了池子资金）。
- **可调余额**（调配前置校验，复审 NF5 已修正，避免重复扣减）：
  ```
  allocatable(p) = max(0, net_position(p))
  ```
  说明：调配一旦发起，OUT 现金**同事务写走**，`net_position(from)` 立即下降——已隐含"未归还的调出额"。故可调余额 = 净头寸的正部，**不再额外减 frozen_out**（否则同一笔调出被扣两次，会把正常项目锁死成 0）。`POST /api/capital/allocate` 校验 `amount <= allocatable(from_project)`，否则 422「可调余额不足」。

### 5.2 资金池核心查询（v2.0）

```sql
-- 池总余额：红冲反向记录 direction 相反、金额相等，参与 SUM 自动抵消，故无需额外过滤（复审 NF3）
SELECT SUM(CASE WHEN direction='IN' THEN amount ELSE -amount END) AS balance
FROM capital_transactions
WHERE deleted_at IS NULL;

-- 各项目净头寸
SELECT p.id, p.name,
  COALESCE(SUM(CASE WHEN ct.direction='IN'  THEN ct.amount ELSE -ct.amount END),0) AS net_position
FROM projects p
LEFT JOIN capital_transactions ct ON ct.project_id=p.id AND ct.deleted_at IS NULL
GROUP BY p.id, p.name;

-- 可调余额：调配一调出即原子移走现金（同事务写 OUT），净头寸已反映未归还调出额，直接取正部（复审 NF5）
SELECT GREATEST(0,
  COALESCE(SUM(CASE WHEN direction='IN' THEN amount ELSE -amount END),0)
) AS allocatable
FROM capital_transactions WHERE project_id=:p AND deleted_at IS NULL;
```

### 5.3 计费与收入确认（billings 生成，对应 F1/W14）

**触发**：点亮后，按月（每月 1 日定时任务，或手动"生成本月计费"）为每个**点亮订单**生成一条 `billings`（计费粒度=订单×期，对应 NF6 唯一键 `(order_id, period_index)`）。**终止规则**（NW3）：仅当 `contract.status IN ('已签','执行中')` 且 `billing_date <= contract.end_date` 时生成；合同进入"已完成/已终止"或越过 end_date 后停止。

**算法**（`utils/billing.py`，纯函数，配单元测试）：

```
monthly_rent     = contract.monthly_rent          # 含税月租
tax_rate         = contract.tax_rate              # 如 0.13
首月 (period_index=1, 点亮日 L):
  days_in_month   = 当月总天数
  days_remaining  = 当月总天数 - day(L) + 1        # 含点亮当日
  amount          = monthly_rent × days_remaining / days_in_month   # 含税，按比例
后续月:
  amount          = monthly_rent                  # 整月
价税分离:
  amount_ex_tax   = round(amount / (1 + tax_rate), 2)
  tax_amount      = amount - amount_ex_tax
```

**示例**：月租 10 万（含税 13%），点亮 2026-09-15 → 首月 amount = 100000 × (30−15+1)/30 = 100000 × 16/30 = 53333.33；不含税 = 53333.33/1.13 ≈ 47197.64；税额 ≈ 6135.69（ex + tax = 53333.33 闭合，经单测校验——注：早期手算误记为 47198.08/6135.25，以单测为准）。

**勾稽回填**：开票时 `billings.invoice_id` 回填、状态→已开；收款时 `billings.capital_transaction_id` 回填、状态→已收款。

### 5.4 折旧计算（对应 W15）

```
total_original_value = quantity × unit_original_value
residual_value       = total_original_value × 0.10
depreciable_value    = total_original_value − residual_value
annual_depreciation  = depreciable_value / 5
monthly_depreciation = annual_depreciation / 12            # = depreciable_value / 60
start_date           = 点亮日 L（点亮同事务写入）
end_date             = L + 5 年（同日）
```

**部分年份**：首月按 `(当月剩余天数/当月总天数) × monthly_depreciation`；末月补齐使累计折旧精确等于 `depreciable_value`（尾差进末月）。按月生成折旧明细（二期报表）；一期在 `assets` 表存年/月折旧额，`status` 到 `end_date` 后置"已提完"。

### 5.5 还款计划自动生成（对应 W13/W6/W21）

**触发**：金租放款（`leasing_processes.status→已放款`）同一事务内，按 `actual_disbursement_amount / annual_rate / term_periods / payment_freq / repayment_method` 自动生成 N 期 `repayments`。

```
P   = actual_disbursement_amount         # 实际放款额（非申请额，W19）
r   = annual_rate
i   = r / periods_per_year               # periods_per_year: 月=12, 季=4, 半年=2
n   = term_periods
第 k 期 (等额本息):
  installment   = P × i × (1+i)^n / ((1+i)^n − 1)
  interest_k    = P_remaining × i
  principal_k   = installment − interest_k
  P_remaining  -= principal_k
第 k 期 (等额本金):
  principal_k   = P / n
  interest_k    = P_remaining × i
due_date_k     = disbursement_date + k × (12/periods_per_year) 月   # 单一真相源 W21
```

**取整与尾差**（NW1）：`installment = round(..., 2)`；等额本息末期 `principal_n = P − Σ_{k<n} principal_k`、`interest_n = installment − principal_n`；等额本金末期微调使 Σprincipal 恰为 P。

放款幂等：`plan_generated` 守卫，重复触发不重复生成（§3.6）。

### 5.6 发票对账（三流勾稽，对应 W12/W18）

**对账维度**（收端示例，销售合同）：

| 维度 | 来源 |
|---|---|
| 合同额 | `contracts.amount`（不含税） |
| 应收（计费） | Σ `billings.amount_ex_tax` WHERE contract_id |
| 已开票 | Σ `invoices.amount_ex_tax` WHERE contract_id AND direction=RECEIVABLE |
| 已收款 | Σ `capital_transactions.amount` WHERE invoice_id in (该合同发票) AND direction=IN |

**差异展示**：`合同 − 应收` / `应收 − 已开票` / `已开票 − 已收款`，逐级标红。

**超开拦截**（W18）：`POST /api/invoices` 前置校验
```
Σ 已存在 invoices.amount_ex_tax(同合同,direction) + new.amount_ex_tax
   <= contracts.amount × (1 + tolerance)     -- tolerance 默认 0.001（0.1%，容合理补充协议，NW9）
超开 → 422，需财务总监审批后放宽（权限矩阵 A），审批记 audit_logs.action='APPROVE_OVERCONTRACT'
```

```sql
-- 对账核心查询（收端，按合同）—— 先各自聚合再 JOIN，避免 m×n 行乘放大（复审 NF4）
WITH b AS (
  SELECT contract_id, SUM(amount_ex_tax) AS billed
  FROM billings WHERE deleted_at IS NULL AND status<>'已红冲' GROUP BY contract_id
), i AS (
  SELECT contract_id, SUM(amount_ex_tax) AS invoiced
  FROM invoices WHERE deleted_at IS NULL AND status<>'已红冲' AND direction='RECEIVABLE' GROUP BY contract_id
)
SELECT c.id, c.contract_no, c.amount AS contract_amt,
  COALESCE(b.billed,0) AS billed, COALESCE(i.invoiced,0) AS invoiced,
  c.amount - COALESCE(b.billed,0) AS gap_billed
FROM contracts c
LEFT JOIN b ON b.contract_id=c.id
LEFT JOIN i ON i.contract_id=c.id
WHERE c.type='SALES';
```

### 5.7 未来 30 天应付汇总（v2.0，含红冲过滤）

```sql
-- 应付 = 金租还款到期 + 采购发票到期
SELECT
  (SELECT COALESCE(SUM(planned_principal+planned_interest),0) FROM repayments
     WHERE due_date BETWEEN current_date AND current_date+interval '30 days'
       AND status='待还' AND deleted_at IS NULL)
  +
  (SELECT COALESCE(SUM(amount),0) FROM invoices
     WHERE direction='PAYABLE' AND status NOT IN ('已付款','已红冲')
       AND due_date BETWEEN current_date AND current_date+interval '30 days'
       AND deleted_at IS NULL)
AS payable_30d;
```

### 5.8 预警规则（v2.0，扩充）

| 预警 | 触发条件 | 级别 |
|---|---|---|
| 资金池余额不足 | 池总余额 < 未来 30 天应付 | 🔴 高危 |
| 流贷即将到期 | 距离还本日 < 15 天 | 🟠 警告 |
| 金租放款延迟 | `disbursement_date` 已过未到账 | 🔴 高危 |
| 调配未归还 | `expected_return_date` 已过且未归还 | 🟠 警告 |
| 金租实付≠申请 | `actual_disbursement_amount` 与 `total_amount` 差异 > 容差 | 🟠 警告 |
| 发票超开 | Σ 已开票 > 合同额 × (1+tolerance) | 🔴 高危 |
| 还款逾期 | `due_date` 已过且 status='待还' | 🔴 高危 |

---

## 6. API 设计

### 6.1 通用约定

- 鉴权：除 `/api/auth/login` 外，所有请求带 `Authorization: Bearer <jwt>`。
- **幂等**：写操作建议带 `Idempotency-Key: <uuid>` 头（放款/调配/点亮/计费/确认收款**必须**带）。命中同 key 回放首次响应（§3.6）。
- 软删除：`GET` 默认仅返回 `deleted_at IS NULL`；`?include_deleted=true` 仅财务总监可用。
- 分页：`?page=1&page_size=20`，响应 `{items, total, page, page_size}`。
- 金额：请求/响应统一传**小数**金额（元），rate 传小数（0.0435）。

### 6.2 错误码

| HTTP | code | 含义 |
|---|---|---|
| 400 | `BAD_REQUEST` | 参数错误 |
| 401 | `UNAUTHORIZED` | 未登录/token 过期 |
| 403 | `FORBIDDEN` | 角色无权 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `ILLEGAL_TRANSITION` | 非法状态迁移 |
| 409 | `IDEMPOTENCY_CONFLICT` | 同 key 不同请求体 |
| 409 | `DUPLICATE` | 动作已执行（重复放款等） |
| 422 | `INSUFFICIENT_ALLOCATABLE` | 可调余额不足 |
| 422 | `INVOICE_OVER_CONTRACT` | 发票超开 |
| 422 | `VALIDATION_ERROR` | 业务校验失败 |
| 500 | `INTERNAL` | 服务端错误 |

统一响应体：`{ "code": "...", "message": "...", "details": {...} }`。

### 6.3 端点清单（主要）

```
# 认证与用户
POST   /api/auth/login                 # 登录，返回 access+refresh
POST   /api/auth/refresh
GET    /api/users                      # 仅总监
POST   /api/users                      # 建号

# 主数据 / 项目 / 合同
GET/POST /api/suppliers  /api/customers  /api/equipment-models  /api/banks
GET/POST /api/projects  /api/projects/{id}
GET/POST /api/contracts  /api/contracts/{id}

# 资金池
GET    /api/capital/transactions
POST   /api/capital/transactions       # 记一笔
GET    /api/capital/summary            # 余额/来源拆分/项目净头寸/可调余额
GET    /api/capital/allocatable?project_id=
POST   /api/capital/allocate           # 跨项目调配（需 Idempotency-Key，财务专员发起+总监审批）

# 金租
GET/POST /api/leasing/processes
GET    /api/leasing/processes/{id}/nodes
PATCH  /api/leasing/nodes/{id}
POST   /api/leasing/processes/{id}/disburse   # 放款（需 Idempotency-Key，生成流水+还款计划）

# 订单 / 交付
GET/POST /api/orders
GET    /api/orders/{id}/stages
PATCH  /api/delivery-stages/{id}       # 点亮完成同事务生成 assets（需 Idempotency-Key）

# 计费 / 发票
POST   /api/billings/generate          # 按月生成计费（需 Idempotency-Key）
GET    /api/billings
GET/POST /api/invoices                 # 超开校验
PATCH  /api/invoices/{id}/pay          # 确认收/付款，回填 capital_transaction_id
GET    /api/invoices/reconciliation    # 三流对账视图

# 还款 / 资产
GET    /api/repayments
PATCH  /api/repayments/{id}            # 确认还款
GET    /api/assets

# 仪表盘 / 审计
GET    /api/dashboard/alerts
GET    /api/audit-logs?entity_type=&entity_id=   # 仅总监
```

### 6.4 关键端点请求/响应

**POST /api/leasing/processes/{id}/disburse**（放款）
```jsonc
// 请求（头带 Idempotency-Key）
{ "actual_disbursement_amount": 48000000.00,
  "disbursement_date": "2026-08-10",
  "note": "实际放款 4800 万，与申请 5000 万差 200 万" }
// 响应 200
{ "capital_transaction_id": "...", "repayments_generated": 20,
  "warning": "实际放款与申请额差异 4.00%" }
// 重复调用同 key → 回放首次响应（不重复生成）
```

**POST /api/capital/allocate**（调配）
```jsonc
// 请求（财务专员发起，status=待审批；或总监直接带 approve=true）
{ "from_project_id":"...", "to_project_id":"...", "amount":5000000.00,
  "allocation_date":"2026-08-01", "expected_return_date":"2026-10-01", "reason":"B 项目付尾款" }
// 可调余额不足 → 422 INSUFFICIENT_ALLOCATABLE
```

---

## 7. 前端设计

### 7.1 路由

```
/login  /  /projects  /projects/:id  /contracts
/capital  /capital/transactions  /capital/allocations
/leasing  /leasing/:id
/orders  /orders/:id
/billings                 # 计费（新）
/invoices  /invoices/reconciliation
/repayments  /assets
/master-data  /users  /audit-logs   # 后两项仅总监可见
```

### 7.2 状态管理（Pinia）

- `authStore`：token、role、用户信息；路由守卫据此过滤菜单与路由。
- 各业务域 store（capital/leasing/invoice...）：列表数据 + 缓存 + 分页。

### 7.3 API 层

- `api/client.ts`：axios 实例；请求拦截注入 `Authorization` 与写操作的 `Idempotency-Key`（composable 生成 uuid）；响应拦截统一处理 401（跳登录）、403/409/422（Naive UI message 提示）。
- 按域拆分 `api/capital.ts` 等，与后端 schema 对齐的 TS 类型在 `types/`。

### 7.4 表单校验

- Naive UI form rules + 业务规则（金额>0、rate∈[0,1)、日期先后）。
- 关键校验前端先做、后端必做（不信任前端）：
  - 调配金额 ≤ 可调余额（前端先查 `/api/capital/allocatable` 预览）。
  - 发票不含税额 = 含税/(1+税率)，自动计算并禁改。
  - 计费生成前预览本期金额。

### 7.5 关键交互

- **金租时间线**：横向 9 节点，灰/蓝/绿/红四态，卡住节点高亮+显示原因。
- **对账表**：三流勾稽，逐级差异标红，悬浮显示金额构成。
- **金额输入**：统一 `AmountInput` 组件，千分位 + 2 位小数，显式标注含税/不含税。

---

## 8. 测试策略（对应 F6）

### 8.1 分层与目标

| 层 | 工具 | 目标 |
|---|---|---|
| 单元 | pytest | 纯计算函数 100%覆盖 |
| 集成 | pytest + httpx + 测试 DB（独立 schema/docker） | API + 事务 + 状态机 |
| E2E | Playwright | 关键业务流程 |
| 总覆盖 | pytest-cov | ≥ 80% |

### 8.2 单元测试重点（纯函数）

- `utils/billing.py`：首月按比例（点亮日跨 28/30/31 天月份）、价税分离、边界（点亮日=月末）。
- `utils/repayment_plan.py`：等额本息/等额本金各期本息、末期尾差、periods_per_year 换算。
- `utils/depreciation.py`：月折旧、首末月按天数、累计精确等于应折旧额。
- `services/reconcile.py`：三流勾稽差异计算、超开判定。
- `utils/payable.py`：未来 30 天应付汇总（跨表）。

### 8.3 集成测试（API + DB）

每个"动作→副作用"链路测：成功路径 + 幂等（重复同 key 不重复生成）+ 状态机非法迁移（409）+ 校验失败（422）：
- 放款 → 生成 1 条流水 + N 期还款 + `plan_generated=true`；重复放款 → 409 DUPLICATE。
- 调配 → 可调余额不足 → 422；成功 → 总余额不变、两项目净头寸此消彼长。
- 点亮 → 同事务生成 assets、`start_date` 正确；重复 → 资产不重复。
- 发票超开 → 422。
- 红冲 → 原记录不可改、反向记录方向相反、审计 `REVERSE` 留痕。
- 调配归还（NW16）→ 生成反向 2 条流水、`capital_allocations` 状态→已归还、总余额不变、两项目净头寸还原。

### 8.4 E2E（Playwright）

登录 → 建项目/合同 → 记资金流水 → 金租 9 节点流转 → 放款 → 订单交付到点亮 → 计费 → 开票 → 确认收款 → 对账无差异 → 还款确认。覆盖 4 角色视角与权限拦截。

### 8.5 对账基准（对应 W24）

以磁盘现有测算 Excel 作为系统数 vs Excel 数的对账基准（一期不自动导入，人工抽查）：
- `庭宇1372台利润表和现金流测算...xlsx`（现金流 sheet）↔ `capital_transactions` + `repayments`。
- `7加7项目投资测算表...xlsx` ↔ 项目 `total_investment` 与现金流。
- `七号项目测算表（商机5090）V5-20260427(1).xlsx`（取最新 V5）↔ 商机 5090 项目全量初始化校验。

> CI 友好（NW10）：把庭宇测算的现金流/还款表 CSV 化作为测试 fixture，集成测试自动断言"系统数 = Excel 数"，避免纯人工抽查无法入 CI。

### 8.6 每模块 DoD（验收标准）

| 模块 | 做完算"验通过" |
|---|---|
| 资金池 | 系统池总余额 = Excel 手算余额；调配后总余额不变、净头寸此消彼长 |
| 金租 | 9 节点全流转可走通；放款生成 N 期且与 Excel 还款表一致 |
| 计费 | 首月按比例金额 = 手算；价税分离正确 |
| 发票对账 | 三流差异表与 Excel 逐笔一致；超开被拦截 |
| 折旧 | 月折旧累计 = 应折旧额（精确到分） |
| 幂等 | 每条副作用链路重复请求不产生重复数据 |
| 审计 | 任意写操作在 audit_logs 可查 before/after |
| 权限 | 越权请求返回 403 |

---

## 9. 部署与运维

### 9.1 Docker Compose（完整）

```yaml
version: "3.9"
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: siegpu
      POSTGRES_USER: siegpu
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: ["pgdata:/var/lib/postgresql/data", "./backups:/backups"]
    networks: [siegpu_net]
    restart: unless-stopped
  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+psycopg://siegpu:${DB_PASSWORD}@db:5432/siegpu
      JWT_SECRET: ${JWT_SECRET}
    volumes: ["./uploads:/app/uploads"]
    depends_on: [db]
    networks: [siegpu_net]
    restart: unless-stopped
  frontend:
    build: ./frontend
    ports: ["8080:80"]
    depends_on: [backend]
    networks: [siegpu_net]
    restart: unless-stopped
volumes: { pgdata: {} }
networks: { siegpu_net: {} }
```

每日备份：宿主机 cron 跑 `docker exec db pg_dump ... > /backups/siegpu-$(date +%F).sql`，保留 30 天；季度离线拷贝。

### 9.2 备份恢复

- RPO ≤ 24h（每日 pg_dump）；RTO ≤ 2h（恢复演练每季度一次，列入运维清单）。
- 恢复验证：还原到测试库，跑资金池余额对账用例。

### 9.3 监控

- 简单：FastAPI `/healthz`；宿主机跑 `docker ps` 心跳脚本。
- 应用内预警（§5.8）通过仪表盘展示；二期接邮件/企业微信。

### 9.4 审计日志运维

- `audit_logs` 仅插入；按年归档（`pg_dump` 单表 → 冷存储）。
- 仅财务总监可读；导出走 `X` 权限并自身被审计。

---

## 10. 开发路线图（v2.0，含前移项）

### 一期（MVP，约 8-10 周）

| 周 | 内容 | DoD |
|---|---|---|
| 1 | 骨架（Docker + FastAPI + Vue + PG）、**users 表 + JWT + RBAC 中间件 + 权限矩阵**、`audit_logs` 基础设施、`idempotency_keys` | 角色越权返 403；写操作有审计 |
| 2 | 主数据 CRUD（供应商/客户/设备/银行）、项目/合同（含级联） | 主数据可维护；合同级联正确 |
| 3-4 | **资金池**（流水/调配/可调余额/预警/仪表盘） | 池余额=Excel；调配净 0 |
| 5 | **金租流程**（9 节点时间线、放款→流水+还款计划自动生成） | 放款生成 N 期与 Excel 一致 |
| 6 | 订单/交付（点亮→资产同事务）、**计费 billings**（按月生成+价税分离） | 计费首月按比例正确 |
| 7 | **发票 + 三流对账 + 超开拦截**、还款确认、折旧计算 | 对账与 Excel 一致 |
| 8 | **测试补齐**（单元/集成/E2E，80%）、**历史数据初始化**（用 Excel 对账）、部署上线 | 各模块 DoD 全绿 |

> 与 v1.0 差异：RBAC/审计/幂等/测试/历史初始化显式纳入一期；工期由 4-6 周→8-10 周（复审 NW14：范围扩约 40%，3-5 人经验不足团队 6-8 周偏紧，按 8-10 周排，或把折旧明细/对账自动级联挪二期）。

### 二期

- 自动化利润测算（复用 Excel 模型）、Excel 导入/导出、通知提醒（邮件/企业微信）、报表模块、折旧明细按月报表。

---

## 11. 风险与缓解（v2.0）

| 风险 | 缓解 |
|---|---|
| 业务需求变化快 | 模块化 + 状态机可配；节点模板可按金租公司覆盖 |
| 金租流程因公司而异 | `leasing_nodes` 动态节点；`repayments` 期数/频率可配（W6） |
| **数据录错** | 软删除 + 红冲（§3.7）；金额类禁硬改；全审计留痕 |
| **重复触发污染资金池** | 幂等两层防护（§3.6） |
| 调配超额 | 可调余额前置校验（§5.1） |
| 发票超开 | 录入拦截 + 总监审批（§5.6） |
| 金租实付≠申请 | `actual_disbursement_amount` + 预警（§5.8） |
| 团队经验不足 | 选型最简；本期文档可直接进入开发；测试兜底 |
| 历史数据工作量大 | 一期只上活跃项目；Excel 作对账基准；历史初始化显式排期 |
| 备份失效 | 季度恢复演练（§9.2） |

---

## 12. 与现有 Excel 资产的映射（按磁盘真实文件，对应 W23）

| Excel 文件（磁盘已验证） | 在新系统中的处理 |
|---|---|
| `采购明细-赛意-宽恒-A.xlsx` | → `orders` + 采购 `contracts` 要素 |
| `赛意信息服务合同主要需要了解的要素.xlsx` | → 合同录入字段模板（销售/采购要素清单） |
| `庭宇1372台利润表和现金流测算-20260609(1).xlsx` | 同一工作簿多 sheet：**现金流 sheet** → `capital_transactions`+`repayments` 对账基准（一期）；**利润表 sheet** → 二期利润测算 |
| `2026年3月AI创新运营部财务报表V2-20260401(4).xlsx` | → 二期报表模块；一期作资金/损益抽查基准 |
| `7加7项目投资测算表（SY）20260427-DR-V1.0(3).xlsx` | → 项目 `total_investment` + 现金流对账基准 |
| `七号项目测算表（商机5090）V5-20260427(1).xlsx`（V5 两份并存：`(1)` 与无 `(1)`；初始化前由财务专员人工确认采用哪份并记录确认人/日期，NW13） | → 商机 5090 项目全量初始化校验基准 |

一期手工初始化（逐条录入主数据与活跃项目历史记录）；批量导入留二期。Excel 文件不删，作对账真相源。

---

## 附录 A：v1.0 → v2.0 变更记录

见 [§0 变更摘要](#0-v10--v20-变更摘要)。19 条变更逐条对应审计 F1–F6 / W6–W24。

### v2.0 复审修订（NF/NW，2026-07-30）

独立复审（`AUDIT-2026-07-30-siegpu-erp-design-v2.md`）发现 6 FAIL（新引入）+ 16 WARNING，已全部处置：

| 编号 | 问题 | 处置 |
|---|---|---|
| NF1 | 调配两流水共用 idempotency_key 撞唯一索引 | 键改 `allocate:{id}:OUT`/`:IN`；整笔幂等交通用层 + allocations 约束 |
| NF2 | chk_reversal CHECK 含子查询 PG 拒绝 | 删 CHECK；方向校验移 service 层 + `is_reversal` 标志 |
| NF3 | 池余额 SQL 引用不存在的 status_raw | 重写：红冲反向记录参与 SUM 自动抵消 |
| NF4 | 对账 SQL 三表 JOIN 行乘放大 | 改 CTE 先聚合再 JOIN |
| NF5 | 可调余额公式重复扣减 | 改 `allocatable=max(0,net_position)`，删 frozen_out |
| NF6 | billings 唯一键与"每订单计费"冲突 | 唯一键改 `(order_id, period_index)` |
| NW1 | installment 取整/末期尾差 | 补 round + 末期吸收尾差 |
| NW3 | 计费无终止规则 | 补 status/end_date 终止条件 |
| NW4 | 三表缺 reversal_of_id | invoices/billings/repayments 各加 reversal_of_id |
| NW5 | rate 无 CHECK 范围 | `CHECK (rate BETWEEN 0 AND 1)` |
| NW6 | ADMIN 角色未定义 | §1.3 注：等价总监全权+用户管理+系统设置，仅初始化/应急 |
| NW7 | 红冲防呆缺失 | 反向记录终态不可再红冲；调配红冲联动 allocation 状态 |
| NW8 | monthly_rent 含税未入例外 | §1.6 + 附录 B 补入 |
| NW9 | tolerance=0 + 审批留痕 | 默认 0.001 + audit action APPROVE_OVERCONTRACT |
| NW10 | Excel 对账难入 CI | 庭宇现金流/还款表 CSV 化做 fixture |
| NW11 | created_by 必填口径矛盾 | 改为仅关键财务表必填，余由 audit_logs 追溯 |
| NW12 | 分域小计错 | 资金域 2 张、交付运营域 6 张 |
| NW13 | V5 两份并存 | 注明初始化前人工确认 + 记录确认人/日期 |
| NW14 | 工期偏紧 | 改 8-10 周（或折旧明细/对账级联挪二期） |
| NW15 | audit REVOKE 含糊 | 应用 role 仅 INSERT/SELECT，REVOKE UPDATE/DELETE/TRUNCATE |
| NW16 | 调配归还无事务/无测试 | §3.6 补归还事务行 + §8.3 补归还测试 |

## 附录 B：单位与量纲全链路对照表

| 字段 | 输入框（前端） | 存储（DB） | 内存/计算 | 引擎消费 | 转换点 |
|---|---|---|---|---|---|
| `annual_rate`（金租/流贷） | 用户输 4.35（%） | `0.04350000`（小数） | 小数 | `i = r/periods_per_year` | 前端 ×0.01 存库；展示 ×100 |
| `residual_rate` | 固定 10% | `0.10000000` | 小数 | `原值 × rate` | 固定常量 |
| `tax_rate` | 13（%） | `0.13000000` | 小数 | `ex = amount/(1+rate)` | 前端 ×0.01 |
| `monthly_rent` | 元（含税） | `DECIMAL(18,2)` 含税 | 含税 | 计费按比例拆出 ex/tax | 计费时 ÷(1+rate)（NW8） |
| 金额 | 元，2 位小数 | `DECIMAL(18,2)` 元 | Decimal | 直接 | 无 |
| `direction`（资金） | 选"收款/付款" | `IN/OUT` | 枚举 | SUM(IN−OUT) | 前端映射 |
| `direction`（票据） | 选"销售/采购" | `RECEIVABLE/PAYABLE` | 枚举 | 对账分组 | 前端映射 |

> 硬约束：所有 `rate` 入库前由前端 ×0.01 转小数；任何"百分数直接入库"均为 bug。

## 附录 C：初始化顺序（历史数据）

1. users（4 角色）→ 2. 主数据（供应商/客户/设备/银行）→ 3. 项目 → 4. 合同（销售+采购级联）→ 5. 历史资金流水（按 Excel 现金流 sheet）→ 6. 金租申请+节点+还款（已放款的）→ 7. 订单+交付（已点亮的同步生成资产）→ 8. 历史发票+计费 → 9. 对账校验（系统数 vs Excel）。

每步录入后立即与 Excel 抽查对账，不一致停下排查（遵循"验证不猜测"）。

---

> **文档版本**：v2.0（含复审修订） | **最后更新**：2026-07-30 | **复审报告**：`AUDIT-2026-07-30-siegpu-erp-design-v2.md`（6 FAIL + 16 WARNING 已全部处置）
