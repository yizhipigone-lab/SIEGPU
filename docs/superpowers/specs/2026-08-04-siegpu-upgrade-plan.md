# SIEGPU ERP 升级方案计划书

> 日期：2026-08-04 | 版本：V2.2（V3.0 需求适配 + 独立审计修订 + 财务裁定落地） | 状态：READY
> 需求基线：财务团队《SIEGPU ERP 系统项目需求说明书 V3.0》（豆包线程，已存档 `doubao-requirements-v3.md`）
> 审计记录：V1.0→V1.1 审计 3H/10M/9L 已处置；V2.0→V2.1 独立审计 1 CRITICAL + 6 HIGH + 9 MEDIUM + 8 LOW 已处置（§10.4）

---

## 0. 执行摘要

### 0.1 升级背景

财务团队需求说明书已迭代至 **V3.0**（2026-08-04）。V3.0 相对 V1.0 新增四个结构性域：

1. **单台设备为最小管理单元**：每台设备唯一 SN，交付 7 节点、转固、折旧、计费、保险分摊、收入确认全部细化到单台；批次降级为"批量作业壳"
2. **金租双模式**：直租 / 售后回租，贯穿立项、采购、预付款、放款、资产权属（表内/表外分叉）
3. **监管账户体系**：金租专属监管账户、月度最低留存额（季度还款 ÷ 3）、到账自动校验、超限划转审批、独立台账
4. **资金池预测**：流入/流出计划归集、多周期预测、预付款缺口测算、多场景模拟、安全线预警

现有 SIEGPU v3.3 已完成基础业务闭环（项目/合同/资金池/金租/交付/计费/发票/对账/测算/审计），但**全系统为批次粒度**（orders 带 quantity，assets 一卡多机，无 SN 概念），V3.0 要求的管理粒度与现有数据模型存在结构性差距。

### 0.2 升级策略：改造而非重做

经评估（详见 §10.1 决策记录），采用**地基重构 + 新旧双轨**路径，不重写系统：

- 现有核心算法（资金池/计费/折旧/还款计划/发票拦截）全部保留，94 pytest + 24 e2e 作为回归安全网
- 一期先做**设备层地基重构**（不改业务行为，只改数据模型粒度），后续新域全部建在单台粒度上
- 旧项目走批次粒度老路径，新项目走设备粒度新路径，双轨并行、自然换代，不搞大爆炸切换

### 0.3 分期总览

分四期推进，总工期 **40-48 周**，每期独立可交付：

| 阶段 | 工期 | 主题 | 交付物 |
|------|------|------|--------|
| **一期** | 8-10 周 | 设备层地基重构 + 金租双模式 | devices 层、一机一卡、节点设备化、leasing_mode 贯穿、备查台账 |
| **二期** | 12-14 周 | 业财一体化核心 | EBS Mock 骨架、收入判定引擎、币种汇率、保险管理、合同深化、预付款、付款管控、通用审批 |
| **三期** | 12-14 周 | 资金合规与核算 | 监管账户、收入确认、全域对账、退货链路、预算管控、资金池预测 |
| **四期** | 8-10 周 | 分析决策与系统完善 | 全维度报表、资源池、测算增强、权限治理、操作说明、性能验证 |

> **期外里程碑（不计入 40-48 周）**：真实 Oracle EBS 对接（入站同步、真实业财对账验收）。本计划四期交付的是 Mock 骨架 + 完整业务侧能力；EBS 入站（主数据双向、资金流水双向、余额回写）待获取真实接口规范后单独立项。

### 0.4 基线校准

> 实际计数（2026-08-04 核实）：后端 **27 张表**（17 个模型文件）、**94 条 pytest**（15 个测试文件）、**24 条 e2e**（17 个 spec）。以下全部以此为准。

### 0.5 现有资产保护（V2.x 修订）

- **不改动**资金池/金租/计费/折旧核心算法公式（资金池红冲置换、计费首月按天折算、价税分离、5 年直线折旧、等额本息/本金、按月/季/半年还款频率）
- **例外（经评审确认）**：`assets` 表从"一卡多机（带 quantity）"拆分为"一机一卡"，属 V3.0 强制要求，允许结构调整 + 迁移脚本；折旧公式不变，仅折旧对象从订单资产包变为单台设备
- `orders` / `delivery_stages` 允许调整归属关系（节点从订单级移到设备级），旧项目保留原路径
- `billings` 唯一索引从 `(order_id, period_index)` 迁移为 `(device_id, period_index)`（按台计费的前提，审计 A1）
- 其余表只做**加字段**式扩展，不改核心字段语义
- 新功能优先建新模块/新文件，遵循项目既有的"独立新文件优先"原则

---

## 1. 差距全景图（基于 V3.0 需求）

### 1.1 模块级覆盖率

```
V3.0 需求 12 模块 vs 现有系统覆盖度：

3.1 项目管理            ████████░░░░░░░░  45%
3.2 主数据管理          █████████░░░░░░░  40%
3.3 采购与付款管理      ██████░░░░░░░░░░  30%（新增预付款管理）
3.4 设备与批次生命周期  ███████░░░░░░░░░  30%（粒度不符：批次→单台）
3.5 销售与收入管理      ██████████░░░░░░  45%
3.6 项目测算中心        ██████████░░░░░░  45%
3.7 融资与资金管理      ████████░░░░░░░░  35%（新增监管账户/资金预测）
3.8 资产与资源池        ████████░░░░░░░░  40%（一机一卡改造）
3.9 发票管理            █████████░░░░░░░  45%
3.10 对账中心           █████░░░░░░░░░░░  22%（7 维要求，现有 1 维）
3.11 报表与看板         ████░░░░░░░░░░░░  18%
3.12 系统管理           ██████░░░░░░░░░░  30%
4. EBS接口              ░░░░░░░░░░░░░░░░   0%
```

### 1.2 逐项差距明细

#### 🔴 P0 — 完全缺失（11 项）

| # | 需求点 | 需求章节 | 现有系统 | 排期 |
|---|--------|---------|---------|------|
| 1 | **单台设备层（devices）** | 2.2 / 3.4.1 | 无 SN 概念，assets 一卡多机 | 一期 W1-2 |
| 2 | **金租双模式（直租/售后回租）** | 2.1 / 2.3.2 | leasing 无模式字段 | 一期 W7-8 |
| 3 | **监管账户体系** | 3.7.2 | 无账户类型/留存规则 | 三期 W1-2 |
| 4 | **资金池预测引擎** | 3.7.4 | 无 | 三期 W11-14 |
| 5 | **预付款管理** | 3.3.2 | 无（payment 只有节点枚举） | 二期 W9-10 |
| 6 | **Oracle EBS 全模块对接** | 第四章 | 无任何 EBS 集成代码 | 二期 W1-2 起 |
| 7 | **收入核算路径判定引擎** | 3.5.2 | 无判定逻辑 | 二期 W3-4 |
| 8 | **币种与汇率管理** | 3.2.5 | 全系统默认人民币，无汇率表 | 二期 W5-6 |
| 9 | **保险管理** | 3.4.4 | 无保险相关表或逻辑 | 二期 W7-8 |
| 10 | **项目预算管控** | 3.1.3 | 无预算相关字段 | 三期 W9-10 |
| 11 | **通用审批流** | 3.1.1 / 3.2.6 / 3.7.2 | 无审批引擎（仅零散 approved_by 字段） | 二期 W11-12 |

#### 🟠 P1 — 严重不足（10 项）

| # | 需求点 | 现有 | 差距 | 排期 |
|---|--------|------|------|------|
| 12 | **资产台账** | assets 一卡多机、点亮建卡 | 一机一卡、上架建卡/点亮起折旧、表外备查台账、退货联动折旧冲回、处置报废 | 一期 W5-6 / 四期 W7-8 |
| 13 | **交付节点** | 6 节点、订单粒度 | 7 节点、设备粒度、批量操作壳、附件、到货验收单+暂估入库 | 一期 W3-4 |
| 14 | **采购退货管理** | 无退货链路 | 单台/批量退货、红字发票、退款核销、预付款追回 | 三期 W7-8 |
| 15 | **对账中心** | 销售三流对账 1 维 | 7 维：+采购四单、资产交付、监管账户、汇兑损益、业财一致性、差异明细；维度 1 补"确认收入" | 三期 W5-6 |
| 16 | **付款管理** | capital_transactions 记一笔 | 三重管控、多对多核销（到单台）、多币种、汇兑损益分摊到单台 | 二期 W11-12 |
| 17 | **收入确认管理** | billings 只是应收计费 | 权责发生制确认、与开收解耦、按项目/批次/单台确认、收入成本配比、外币折算 | 三期 W3-4 |
| 18 | **经营看板与报表** | Dashboard 基础 KPI | 资金预测概览、监管账户报表、预付款台账、单台全成本表、毛利/损益/核算审计报表 | 三期 W9-10 / 四期 |
| 19 | **采购/销售合同管理** | 基础 CRUD | 三类采购合同、条款（定价/质保/违约/预付款比例）、变更/终止管理、EBS 同步 | 二期 W9-10 |
| 20 | **收款管理** | 发票侧核销 | 收款登记区分账户（普通/监管）、待认领款项、多对多核销到单台 | 三期 W1-2 |
| 21 | **采购发票进项侧** | 发票池有 PAYABLE 方向和红冲 | 进项税额独立核算（匹配总额/净额税务口径）、发票认证/抵扣状态全流程 | 二期 W11-12 |

#### 🟡 P2 — 需要增强（11 项）

| # | 需求点 | 差距 | 排期 |
|---|--------|------|------|
| 22 | 项目全景视图 | 三级穿透（项目→批次→单台）、含监管账户余额/资金预测 | 四期 W3-4 |
| 23 | 子项目层级 | 缺 project.parent_id，需求 3.1.1 要求层级汇总 | 一期 W1-2（随 projects 加字段） |
| 24 | 客户/供应商档案 | 信用等级/合作资质/评级、供应商金租机构标记+合作模式、EBS 同步 | 二期 W9-10 |
| 25 | 产品/设备型号主数据 | 计费模式/基准单价/资源属性（自购/金租/转售）标记 | 一期 W1-2（随 devices） |
| 26 | 资金成本测算工具 | 独立工具（还款方式/周期切换、实际年化、方案比选、月度最低留存额输出、按批次/设备放款拆分测算、同步台账与预测模型） | 四期 W5-6 |
| 27 | 利润测算模型 | 全周期成本（运输/保险/运维电费带宽/资金占用）、年度拆分、单台残值、预算vs实际 | 四期 W5-6 |
| 28 | 融资项目跟踪 | 分类（金租直租/回租/流贷/项目贷款）、放款成本分摊到单台、到期预警 7/15 天、逾期罚息、材料归档 | 一期 W7-8（分类/归档）/ 三期 W1-2（预警罚息）/ 三期 W11-14（分摊） |
| 29 | 资源池管理 | 设备级状态视图（在途/压测/可用/已占用）、权属标记（表内/金租表外/转售表外） | 四期 W5-6 |
| 30 | 权限管理 | require_role() 仅 3/83 端点接入、缺数据权限（项目+部门）、资金/监管账户操作单独授权 | 四期 W7-8 |
| 31 | 批次全景/进度看板 | 批次汇总+单台穿透视图 | 一期 W3-4（基础版）/ 四期 W3-4（完整版） |
| 32 | 基础规则配置 | 单据编号规则、数据字典、金租规则参数（留存规则/预付款规则/还款周期） | 二期 W11-12 |

> **散项落点包**（需求有、单项较小，在对应章节各给落点）：设备硬件配置字段（§2.1）、批次移出节点约束（§2.1）、设备状态物化列同步规则（§2.1）、项目状态"筹备中"口径（§2.1）、到货验收单/暂估入库（§2.2）、保费摊销/续保提醒/理赔记录（§3.4）、销售侧变更联动（§3.5）、测算定稿同步立项基准（沿用现有多版本同步能力，§5.3 复核）、资产处置报废（§5.4）、资金来源构成分析（§5.2）、关键数据加密（§5.4）、百万级单据性能口径（§5.4）。

#### ✅ 已较好覆盖（保留不动）

- 项目基础 CRUD + 向导式工作台（18 步/15 步模板，表驱动通用引擎）
- 合同基础 CRUD（销售/采购，含级联）
- 资金池模型（统一账本、调配/归还、红冲、流贷/自有→金租置换）
- 金租 9 节点流程 + 放款 + 还款计划自动生成（等额本息/本金，**已支持月/季/半年频率**，`utils/repayment_plan.py` FREQS_PER_YEAR）
- 计费 billings（按月、首月按天折算、价税分离）
- 发票池 + 三流对账 + 超开拦截 + OCR + 红冲（reversal_of_id 留痕）
- 利润测算（IRR/NPV/回收期/多版本/测算vs实际/定稿同步）
- 操作审计日志（audit_logs + step_audit_logs，17 种 action）
- 折旧计算（5 年直线法、残值 10%、末期吸收尾差；**注：折旧无按天折算，按天折算的是计费首月**）
- 预警规则（8 条）
- 客户确认（service_confirmations，计费↔开票中间门）

---

## 2. 一期：设备层地基重构 + 金租双模式（8-10 周）

> **目标**：把数据模型从批次粒度升级为单台粒度，不动业务行为；金租模式字段全链路贯穿
> **关键词**：devices 层、一机一卡、节点设备化、双轨兼容、leasing_mode、备查台账
> **原则**：本期不做任何 V3.0 新功能（保险/预付款等都在后期），纯地基。94 pytest + 24 e2e 每期结束必须全绿。

### 2.1 Week 1-2：devices 实体层 + 主数据字段

**新增文件**：
```
backend/app/models/device.py               # 设备模型
backend/app/services/device_service.py      # 设备服务
backend/app/api/v1/endpoints/devices.py     # 设备端点
backend/app/schemas/device.py
backend/app/tests/test_device.py
frontend/src/views/DevicesView.vue          # 设备清单页
```

**新增表**：

**devices** — 单台设备档案（核心新实体）
| 字段 | 类型 | 说明 |
|------|------|------|
| sn | VARCHAR(50) UNIQUE | 设备 SN 编码（一期硬编码规则 `GPU-{yyyymm}-{seq5}`；二期 doc_number_rules 建成后回迁配置化） |
| project_id | UUID FK→projects | 强制关联项目 |
| order_id | UUID FK→orders | 来源采购订单 |
| batch_id | UUID FK→orders | 归属批次（复用 orders 作为批次载体，见下） |
| sales_contract_id | UUID FK→contracts | 绑定销售合同（销售签约/批次挂载时回填；点亮按台计费的定位依据，审计 A1/A13） |
| monthly_price | DECIMAL(18,2) | 单台月计费额（绑定销售合同时快照自合同，合同变更时联动调整） |
| equipment_model_id | UUID FK→equipment_models | 设备型号 |
| config | JSONB | 硬件配置（需求 3.4.1 设备档案字段） |
| supplier_id | UUID FK→suppliers | 供应商 |
| leasing_mode | VARCHAR(20) | 自有/直租/售后回租（快照自项目，可单台调整） |
| purchase_value | DECIMAL(18,2) | 采购原值（单台） |
| prepayment_amount | DECIMAL(18,2) | 预付款分摊金额 |
| status | VARCHAR(20) | 当前节点状态——**物化列**（= 最新已完成 stage 的派生，由状态机单点维护，禁止业务代码直接写，审计 A24） |
| ownership | VARCHAR(20) | 权属（表内自有/金租表外/转售表外），上架时判定 |

**batch_devices** — 批次-设备组合关系（留痕）
| 字段 | 类型 | 说明 |
|------|------|------|
| batch_id | UUID FK→orders | 批次 |
| device_id | UUID FK→devices | 设备（同一台设备全局仅允许一条 active 记录） |
| action | VARCHAR(10) | 加入/移出 |
| active | BOOLEAN | 是否当前生效 |
| operated_by | UUID FK→users | 操作人 |

> **移出约束**：仅设备未进入关键节点（seq≥5 上架）前可移出，service 层强制校验（需求 3.4.2）。

**off_balance_registers** — 表外设备备查台账（独立于 assets，避免污染折旧汇总，审计 A17）
| 字段 | 类型 | 说明 |
|------|------|------|
| device_id | UUID FK→devices | 表外设备（直租/售后回租租回期/转售） |
| register_type | VARCHAR(20) | 金租直租/售后回租/转售 |
| leasing_process_id | UUID FK | 关联融资项目 |
| start_date / end_date | DATE | 表外期间 |
| note | TEXT | |

> **批次载体决策**：批次复用现有 `orders` 表（它本就承载合同关联+交付链路），不另建 batches 表。`orders.is_batch=true` 标记组合批次；批次行放宽 `equipment_model_id/quantity/unit_price/total_amount` 为可空（批次可跨型号、跨采购订单组合，审计 A4），其汇总值由批内设备聚合派生，不手填。

**现有表加字段**（一期共 7 张）：
| 表 | 新增字段 | 说明 |
|----|---------|------|
| projects | `business_type VARCHAR(20)` | 经营租赁/转售/自营（收入判定 R1 输入） |
| projects | `leasing_mode VARCHAR(20)` | 自有/直租/售后回租（立项时定，R1 输入） |
| projects | `parent_id UUID FK→projects` | 子项目层级（需求 3.1.1） |
| projects | `financing_plan JSONB` | 融资方案摘要 |
| projects | status 枚举补"筹备中" | 与需求 3.1.1 状态口径对齐（现有默认"进行中"保留为迁移默认） |
| equipment_models | `resource_attr VARCHAR(20)` | 资源属性（自购资产/金租资产/转售资源） |
| equipment_models | `billing_modes JSONB` | 计费模式（按时/天/月）+ 基准单价 |
| suppliers | `is_leasing_org BOOLEAN` + `leasing_coop_modes JSONB` | 金租机构标记 + 合作模式（直租/回租） |
| orders | `is_batch BOOLEAN` + `batch_name VARCHAR(100)` + `batch_status VARCHAR(20)` | 批次标记 + 批次聚合状态（**独立字段，不复用 orders.status**，审计 A3） |
| contracts | `leasing_mode VARCHAR(20)` | 合同模式快照 |
| leasing_processes | `leasing_mode` + `financing_type`（金租直租/金租回租/银行流贷/项目贷款）+ `materials JSONB` | 模式/分类/材料归档 |
| billings | `device_id UUID FK→devices` | 按台计费（审计 A1） |

**设备导入**：Excel 批量导入设备清单（复用 `excel_service.py` 模式），自动生成 SN + 档案；支持单台新增/编辑。

### 2.2 Week 3-4：交付节点设备化（6→7 节点）

**新增表**：

**device_stages** — 设备节点状态（设备粒度新路径）
| 字段 | 类型 | 说明 |
|------|------|------|
| device_id | UUID FK→devices | |
| stage | VARCHAR(20) | 订货/在途/到货/己方压测/上架/客户压测/点亮验收 |
| seq | INTEGER | 1-7 |
| status | VARCHAR(20) | 未开始/进行中/已完成/不合格 |
| planned_date / actual_date | DATE | |
| attachment_path | VARCHAR(500) | 验收报告/物流单/压测报告附件 |
| notes | TEXT | |

**设备状态机**（`device_service.py`，纯函数 + 测试）：
```
订货 → 在途 → 到货 → 己方压测 → 上架 → 客户压测 → 点亮验收
              │         │不合格      │
              ▼         ▼            ▼（触发：转固FA卡 / 备查台账）
        到货验收单   退换货流程      点亮验收（触发：计费起点 + 折旧起点 + 放款条件 + 资金预测计划项）
        +暂估入库状态
```

**批量操作壳**：批次维度批量推进节点 → 批量更新批内所有设备；支持单台单独推进。批次整体状态聚合写入 `orders.batch_status`（全部点亮→批次点亮，等）。

**双轨兼容（关键设计，审计 A3 三条纪律）**：
1. `orders.is_batch=true` 的订单**不生成** 6 条 delivery_stages（`create_order` 加分支），节点只走 device_stages
2. 旧触发入口——`order_service.light_on()`、`billing_service.generate_billing()`、对应公开端点——**强制过 `resolve_flow_type` 闸**：设备粒度订单直接拒绝并提示走设备路径，防止"批次点亮 + 单台点亮"双重建卡、双重出账
3. 批次聚合状态写 `orders.batch_status` 独立字段；`orders.status="已点亮"` 仅旧路径使用

**`resolve_flow_type(order)` 判定依据**：以订单经 `devices.batch_id` 关联到设备为准；**只升不降**——设备一旦挂入批次，即使后续移出也保持新路径（用 `orders.flow_type` 字段固化首次判定结果，避免中间态翻转，审计 A4）。

**向导工作台适配（审计 A2）**：
- 新增"设备粒度项目"向导模板（`device-flow-7stage`）：completion_check 指向 device_stages/devices 表（引擎的 `_TABLE_CLASSES` 映射补登记）
- 模板选择随项目 flow_type 自动匹配；旧 18/15 步模板不动
- 列入一期交付物，避免新项目走工作台时检查项永远查不到数据

### 2.3 Week 5-6：资产一机一卡 + 计费/折旧按台

**assets 表改造**（§0.5 例外项）：
| 改动 | 说明 |
|------|------|
| 新增 `device_id UUID FK→devices UNIQUE` | 一机一卡（仅固定资产卡入 assets；备查台账走 off_balance_registers，本约束不冲突，审计 A17） |
| 新增 `operation_status VARCHAR(20)` | 已转固未运营 / 运营中（折旧起点门控）/ 已处置 |
| `quantity` 保留但新数据恒为 1 | 向后兼容，不删字段 |

**转固与折旧分离**（需求 3.8.1 + 3.4.3）：
- 设备进"上架"：按 `ownership` 判定 → 表内：生成资产卡（`operation_status=已转固未运营`）；表外：写 off_balance_registers（**不进 assets、不同步 EBS FA 自有资产**）
- 设备"点亮验收"：`operation_status→运营中`，折旧从点亮月起算（公式不变：5 年直线、残值 10%、末期吸收尾差）
- 旧路径不变：6 节点项目仍是点亮同事务建卡并起折旧

**计费按台启动（审计 A1 三件套）**：
1. **唯一索引迁移**：`billings` 现有 `uq_billing_period(order_id, period_index)` 唯一索引迁移为 `(device_id, period_index)`；`billing_service` 服务层同期重复校验同步改为设备维度（旧路径校验保留按 order）
2. **金额来源**：单台月租 = `devices.monthly_price`（绑定销售合同时从合同快照；合同变更时按变更单联动调整并留痕）——不再依赖合同级单一 `monthly_rent`
3. **起点**：按单台点亮日期各自起算（首月按天折算公式复用，仅起点从订单点亮日变为设备点亮日）

**历史数据迁移**（`alembic` data migration + 校验脚本）：
- 存量 assets（一卡多机）→ 按 quantity 生成对应数量 devices（SN 按规则补发）→ 拆分为一机一卡（均摊原值）
- 迁移后校验：Σ单台原值 == 原资产包原值、折旧总额前后一致
- 当前为内部测试数据，迁移量小；生产切换前需全量备份

### 2.4 Week 7-8：金租双模式贯穿

**权属分叉逻辑**（`device_service.settle_ownership()`，上架时执行）：
```
projects.leasing_mode == "自有"     → ownership = 表内自有 → 转固 FA 卡
projects.leasing_mode == "直租"     → ownership = 金租表外 → off_balance_registers
projects.leasing_mode == "售后回租" → 自有阶段先转固；回租出售时：
    资产 operation_status→已处置（按出售日折旧截断，公式复用）
    + off_balance_registers 建档 + 确认长期应付款（leasing_processes 关联）
    + 预付款标记"已结转"（预付款模块在二期，本期留字段和钩子）
```

**放款条件联动**：设备"点亮验收"→ 更新批次放款条件达成计数；达到批次放款阈值 → 触发放款申请待办（接现有 leasing 流程）。

**融资分类**：leasing_processes 的 financing_type/leasing_mode/materials 字段本周落库 + 表单录入（到期预警与罚息在三期 §4.1）。

### 2.5 Week 9-10：一期联调 + 回归

- 端到端：立项（含 leasing_mode）→ 采购下单 → 设备导入 → 批次组合/移出 → 7 节点推进（批量+单台）→ 上架转固/备查 → 点亮 → 按台计费 → 按台折旧
- 双轨验证：旧 6 节点项目全流程回归不失效；旧触发入口闸验证（设备粒度订单调 light_on 被拒）
- 向导新模板全流程走查；历史数据迁移脚本演练 + 校验
- 94 pytest + 24 e2e 全绿 + 新增测试 ≥ 25 条

### 2.6 一期交付物清单

| 类别 | 交付物 | 验收标准 |
|------|--------|---------|
| 数据模型 | **4 张新表**（devices/batch_devices/device_stages/off_balance_registers）+ **7 张表字段扩展**（projects/equipment_models/suppliers/orders/contracts/leasing_processes/billings）+ assets 结构改造 + billings 唯一索引迁移 | Alembic 迁移可正向/回滚；迁移校验脚本通过 |
| 后端 | device_service + 设备状态机 + 权属分叉 + 按台计费/折旧 + 双轨闸 | pytest 新增 ≥ 25 条；状态机/权属判定纯函数 100% 覆盖；现有 94 条全绿 |
| 前端 | 设备清单页 + 批次组合/移出 + 批量节点操作 | 新增 4 条 e2e |
| 工作台 | 设备粒度向导模板（device-flow-7stage） | 新项目模板全流程 e2e 通过 |
| 兼容性 | 双轨并存 | 旧项目 e2e 不失效；双计防护测试（同批设备不出现重复资产/重复账单） |

---

## 3. 二期：业财一体化核心（12-14 周）

> **目标**：打通"业务→财务"数据断点，系统具备合规核算能力
> **关键词**：EBS Mock 骨架、收入判定、币种汇率、保险、合同深化、预付款、付款管控、通用审批

### 3.1 Week 1-2：EBS 接口 Mock 骨架

**新增文件**：
```
backend/app/services/ebs_client.py         # EBS HTTP Client（Mock 实现）
backend/app/models/ebs_sync.py              # 同步日志 + 字段映射模型
backend/app/services/ebs_sync_service.py    # 同步调度服务
backend/app/api/v1/endpoints/ebs.py         # EBS 接口管理端点
backend/app/schemas/ebs.py
frontend/src/views/EbsMonitor.vue           # EBS 同步监控页
```

**新增表**：

**ebs_field_mappings** — 字段映射配置
| 字段 | 类型 | 说明 |
|------|------|------|
| entity_type | VARCHAR(50) | SIEGPU 实体（customer/supplier/contract/invoice/asset/payment/prepayment/lease/goods_receipt...） |
| siegpu_field | VARCHAR(100) | SIEGPU 字段名 |
| ebs_field | VARCHAR(100) | EBS 对应字段名 |
| transform_rule | VARCHAR(50) | DIRECT/FORMULA/LOOKUP |
| transform_config | JSONB | 转换参数 |

**ebs_sync_logs** — 同步日志
| 字段 | 类型 | 说明 |
|------|------|------|
| entity_type | VARCHAR(50) | |
| entity_id | UUID | |
| entity_version | VARCHAR(64) | 实体内容 hash（幂等/乱序处理用，Mock 期即养成） |
| direction | VARCHAR(20) | SIEGPU→EBS / EBS→SIEGPU |
| sync_type | VARCHAR(30) | 实时/批量 |
| status | VARCHAR(20) | 成功/失败/待重试 |
| request_payload / response_payload | JSONB | |
| error_message | TEXT | |
| retry_count | INTEGER | |
| synced_at | TIMESTAMPTZ | |

**Mock 策略**：
- 标准接口（10 个 sync 方法，覆盖需求 4.2 六类业务域）：`sync_customer / sync_supplier / sync_contract / sync_invoice / sync_asset / sync_payment / sync_prepayment / sync_lease_disbursement / sync_repayment / sync_goods_receipt`（采购入库，需求 4.2 采购应付类）
- Mock 返回 `{"status": "MOCK_SUCCESS", "ebs_reference": "MOCK-EBS-{uuid}"}`；`EBS_MOCK_MODE=true/false` 切换
- 同步粒度按 V3.0 接口清单：资产类到**单台设备级**、采购应付类支持**批次+单台行级**、融资核算类到项目/批次级
- **范围说明**：Mock 阶段仅 SIEGPU→EBS 出站；EBS→SIEGPU 入站属期外里程碑（§0.3）
- **前置动作（Week 1 即启动）**：向 IT/EBS 团队申请接口规范（协议/认证/响应结构/错误码）+ 测试环境权限；请财务按 EBS 实际科目表评审字段映射配置，不等后期

**EbsMonitor.vue**：映射配置编辑、同步日志查询、失败单据批量重试、同步统计。

### 3.2 Week 3-4：收入核算路径判定引擎

**新增文件**：
```
backend/app/services/revenue_judge_service.py
backend/app/utils/revenue_rules.py          # 纯函数规则
backend/app/tests/test_revenue_judge.py
```

**contracts 增加字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| pricing_authority | VARCHAR(20) | 定价权（自主定价/客户定价/上游定价） |
| inventory_risk_bearer | VARCHAR(20) | 存货风险承担方（我方/客户/上游） |
| principal_role | VARCHAR(20) | 主要责任人/代理人 |
| revenue_method | VARCHAR(20) | 核算路径：总额法/净额法/经营租赁/服务费（系统判定+人工确认） |
| method_judge_basis | TEXT | 判定依据（自动生成，不可编辑） |
| method_confirmed_by / method_confirmed_at | UUID / TIMESTAMPTZ | 确认留痕 |

**判定规则**（优先级从高到低，命中即停）：
```
R1（经营租赁-自有）：projects.business_type=="算力经营租赁" AND projects.leasing_mode=="自有"
    AND 合同类型==SALES → 经营租赁（表内资产出租）
R1b（转租赁-金租）：business_type=="算力经营租赁" AND leasing_mode IN ("直租","售后回租")
    → 服务费（按月确认）（财务已裁定 2026-08-04：收客户租金全额按服务费逐月确认收入；
      我方付金租的租金按月进成本，收入成本同期配比；不走经营租赁/融资租赁转租赁口径）
R2（净额法）：pricing_authority=="上游定价" AND inventory_risk_bearer=="上游" AND principal_role=="代理人" → 净额法
R3（总额法）：pricing_authority=="自主定价" AND inventory_risk_bearer=="我方" AND principal_role=="主要责任人" AND 未命中 R1 → 总额法
R4（兜底）：→ "待判定"，推送财务总监人工判定
```
> R1 输入来自项目立项字段（一期已加 `projects.business_type` / `leasing_mode`），合同保存判定结果快照。解决"合同签约时资产未存在，权属无从判定"的时序问题。

**前端**：合同表单"核算判定信息"区，三必填下拉，实时预览判定结果+依据；人工覆盖需填原因（记 audit_logs）。

**EBS 关联**：合同审核生效后判定结果随合同同步（Mock），`entity_type='contract_revenue_method'`。

### 3.3 Week 5-6：币种与汇率管理

**新增表**：

**currencies**（code UNIQUE / name / symbol / is_base / active）

**exchange_rates** — 汇率表
| 字段 | 类型 | 说明 |
|------|------|------|
| from_currency / to_currency | VARCHAR(10) | 目标币默认 CNY |
| rate_type | VARCHAR(20) | 记账汇率/发票汇率/结算汇率 |
| rate | DECIMAL(18,8) | |
| effective_date | DATE | 支持按月/按日 |
| source | VARCHAR(50) | 央行/银行/手动 |

**exchange_gain_loss_rules**（scenario / gl_account_code / description）

**现有表加字段（含审计修正——汇兑损益公式的输入补齐）**：
| 表 | 新增字段 | 说明 |
|----|---------|------|
| contracts | `currency_code` + `booked_rate DECIMAL(18,8)` | 合同币种 + 记账汇率 |
| invoices | `currency_code` + `invoice_rate DECIMAL(18,8)` | **发票汇率（汇兑损益计算的必要输入）** |
| billings | `currency_code` + `booked_rate` | 计费币种 + 记账汇率 |
| capital_transactions | `currency_code` + `settlement_rate` + `base_amount` | 结算币种/汇率/本位币金额 |

**汇兑损益自动计算**（service 层）：
- 付款/收款核销时：`diff = amount × (invoice_rate − settlement_rate)` → `capital_transactions.category="汇兑损益"` 记录 + 生成凭证提示
- 按 V3.0 3.3.3：汇兑损益**按成本占比分摊至对应设备**（经 payment_settlements 的设备维度，见 §3.6）
- 外币重估场景留接口，本期不实现

### 3.4 Week 7-8：保险管理（设备粒度）

**新增表**：

**insurance_policies** — 保单管理
| 字段 | 类型 | 说明 |
|------|------|------|
| project_id / batch_id | UUID FK | 关联项目/批次 |
| policy_type | VARCHAR(20) | 货物运输险/财产一切险 |
| policy_no / insurer_id | VARCHAR(100) / UUID FK→suppliers | 承保公司 type=保险公司 |
| insured_amount / premium_rate / premium_amount | DECIMAL | |
| start_date / end_date | DATE | |
| status | VARCHAR(20) | 生效中/已到期/已理赔/已终止 |
| trigger_event | VARCHAR(50) | 批次在途/点亮验收 |
| cost_allocation | VARCHAR(20) | **资产原值 / 长期待摊费用**（V3.0 口径） |
| amortization_months | INTEGER | 长期待摊费用摊销月数（cost_allocation=长期待摊费用时必填） |
| claims | JSONB | 理赔记录（理赔日期/金额/说明，需求 3.4.4） |
| file_path | VARCHAR(500) | 保单扫描件 |

**insurance_policy_devices** — 保费设备分摊
| 字段 | 类型 | 说明 |
|------|------|------|
| policy_id | UUID FK | |
| device_id | UUID FK→devices | |
| allocated_amount | DECIMAL(18,2) | 按设备价值占比分摊 |

**insurance_configs**（policy_type / default_rate / insured_ratio / insurer_id / cost_allocation / active）

**自动投保触发**：
- 批次内设备进"在途"→ 按批次设备总价值 × insured_ratio 生成运输险保单（待确认）→ 保费按设备价值占比分摊到单台
- 单台"点亮验收"→ 财产一切险投保提醒，绑定对应资产卡
- **保费进资产原值的折旧交互**：仅允许在设备**点亮前**归集进原值（转固后到点亮前窗口）；点亮后产生的保费一律走长期待摊费用，避免触动折旧算法。此约束写入 insurance_service 校验
- **保费摊销**：长期待摊费用按 amortization_months 逐月摊销（复用折旧月度引擎模式），摊销计划同步生成资金预测费用计划项（§4.6 数据源）
- **续保提醒**：alert_service 新增"保单到期前 30 天"规则；理赔登记更新 claims JSONB + status

### 3.5 Week 9-10：合同深化 + 预付款管理

**新增表**：

**contract_amendments**（contract_id / amendment_type / before_value JSONB / after_value JSONB / reason / effective_date / approved_by / status）
- 采购侧：变更生效后自动更新批次、应付计划、预付款计划，同步 EBS（Mock）
- **销售侧**：变更生效后自动调整 billings 计划（未出账期间）、应收余额、收入确认草稿（三期产物，预留钩子），同步 EBS 应收单据调整（Mock）（审计 A18）

**contract_terminations**（contract_id / termination_type / reason / settlement_amount / penalty_amount / effective_date / approved_by / status）——终止联动应付调整、退货流程、预付款清算，同步 EBS 关闭采购订单（Mock）

**prepayments** — 预付款（需求 3.3.2，全新模块）
| 字段 | 类型 | 说明 |
|------|------|------|
| project_id / contract_id / batch_id | UUID FK | |
| leasing_mode | VARCHAR(20) | 快照（直租/回租处理逻辑分叉） |
| apply_amount / paid_amount | DECIMAL(18,2) | 申请/实付 |
| settled_amount | DECIMAL(18,2) | 已核销金额（由 payment_settlements 聚合回写，审计 A16） |
| ratio | NUMERIC(10,8) | 预付款比例（合同条款） |
| status | VARCHAR(30) | 待审批/已支付/待退回/已退回/已结转/已核销 |
| refund_mode | VARCHAR(20) | 全额退回/结转下一批（直租专用） |
| carry_to_order_id | UUID FK→orders | 结转目标批次 |
| capital_transaction_id | UUID FK | 支付流水 |

> 预付款可用余额 = `paid_amount − settled_amount`（派生口径，付款申请扣减校验用）。

**预付款流程**：
```
申请(按合同比例) → 审批(走通用审批) → 普通资金池支付 → 
  直租：金租放款到账+设备确权 → 退回待办（全额退回资金池 / 结转下一批采购）
  回租：受让款到账 → 自动标记"已结转"，纳入采购成本
到票/结算 → 核销应付账款（进 payment_settlements，按台分摊）
```

**合同其他增强**：`contracts` 加 `purchase_type`（硬件/上游算力/运维服务）、`delivery_terms`/`warranty_terms`/`penalty_terms`、`prepayment_ratio`、销售合同 `collection_account_type`（监管账户/普通账户）；合同详情页聚合批次/设备进度、预付款、发票、付款、变更/终止时间线、EBS 状态。

### 3.6 Week 11-12：付款三重管控 + 通用审批 + 基础规则 + 进项侧

**新增表**：

**approvals** — 通用审批（单级，多级别后置）
| 字段 | 类型 | 说明 |
|------|------|------|
| biz_type | VARCHAR(50) | **项目立项**/付款申请/预付款/预算调整/监管划转/合同变更/收入确认... |
| biz_id | UUID | 业务单据 ID |
| action | VARCHAR(30) | 提交/通过/驳回 |
| status | VARCHAR(20) | 待审批/已通过/已驳回 |
| requested_by / approved_by | UUID FK→users | |
| reason | TEXT | 驳回/覆盖原因必填 |

> 项目立项走 approvals 单级审批（需求 3.1.1 多级审核本期单级落地，多级留扩展字段后置）。**提交级校验**：所有业务单据创建时 `project_id` 非空强制校验（需求"未关联项目号的单据无法提交审核"），在 schemas 层统一加。

**payment_requests**（project_id / contract_id / batch_id / invoice_id / payment_node（到货/验收/质保） / request_amount / currency_code / requested_by / status）——付款申请自动**扣减对应预付款可用余额**（paid − settled）

**payment_settlements** — 核销分配表（多对多核心，含设备维度）
| 字段 | 类型 | 说明 |
|------|------|------|
| capital_transaction_id | UUID FK | 一笔付款/收款流水 |
| invoice_id | UUID FK→invoices | 核销目标发票（**可空**：待认领收款、预付款冲抵场景无发票，审计 A16） |
| batch_id | UUID FK→orders | 核销目标批次（无发票场景的目标维度，可空） |
| prepayment_id | UUID FK→prepayments | 核销预付款（可空） |
| device_id | UUID FK→devices | 分摊到单台（可空，按金额占比分摊时逐台多行） |
| amount | DECIMAL(18,2) | 本行核销金额 |

> 支撑 V3.0："一笔付款核销多合同/多批次/多台设备，多笔付款核销同一批次/单台"；收款核销复用同表。

**付款流程**：申请 → 审批（approvals）→ 登记（capital_transactions，多币种+回单）→ 核销（payment_settlements + invoice 回填 + 汇兑损益计算分摊）。

**采购发票进项侧**（需求 3.3.4，审计 A10）：`invoices` 加 `certification_status VARCHAR(20)`（未认证/已认证/已抵扣）+ `certification_date`；进项税台账查询视图（按项目/供应商/期间汇总进项税额，区分总额法/净额法口径标签）；认证/抵扣动作记 audit_logs。

**基础规则配置**：
- `doc_number_rules` 单据编号规则表（前缀+日期+流水），应用于批次号/合同号/付款单号，**并回迁一期硬编码的 SN 规则**（审计 A8）
- `leasing_rule_configs` 金租规则参数表（留存比例、还款周期默认、预付款规则）

**二期联调（W13-14）**：立项（审批）→ 主数据 → 合同（判定+币种）→ 采购 → 预付款 → 设备 7 节点 → 保险触发分摊 → 点亮按台计费 → 开票（含进项认证）→ 付款核销 → 三流对账；EBS Mock 日志完整性；汇兑损益 golden 算例。

### 3.7 二期交付物清单

| 类别 | 交付物 | 验收标准 |
|------|--------|---------|
| 数据模型 | **16 张新表**（详见下注）+ 4 张表字段扩展（contracts/invoices/billings/capital_transactions） | Alembic 可回滚；现有测试全绿 |
| 后端 | 收入判定引擎 + 汇兑损益 + 保险分摊 + 预付款 + 付款管控 + 审批 + 进项侧 | pytest 新增 ≥ 35 条；判定/汇兑/分摊算法 100% + golden 算例 |
| 前端 | EBS 监控、币种汇率、保险、预付款、付款管理 5 个新页 + 合同表单增强 | 新增 6 条 e2e |
| EBS Mock | 出站 6 类业务域（10 个 sync 方法）+ 映射 + 日志（含 entity_version） | Mock 全链路跑通 |

> 注：新表准确计数 = ebs_field_mappings、ebs_sync_logs、currencies、exchange_rates、exchange_gain_loss_rules、insurance_policies、insurance_policy_devices、insurance_configs、contract_amendments、contract_terminations、prepayments、approvals、payment_requests、payment_settlements、doc_number_rules、leasing_rule_configs，共 **16 张**。

---

## 4. 三期：资金合规与核算（12-14 周）

> **目标**：监管账户合规、权责发生制核算、全域对账、资金预测
> **关键词**：监管账户、收入确认、7 维对账、退货、预算、资金池预测

### 4.1 Week 1-2：银行账户 + 监管账户 + 收款管理 + 还款预警

**新增表**：

**bank_accounts** — 公司银行账户（需求 3.2.4；与现有 `Bank` 模型区分——那是资金方/授信主数据）
| 字段 | 类型 | 说明 |
|------|------|------|
| account_no / account_name / bank_name | VARCHAR | 开户行信息（account_no 加密存储，需求 5.3） |
| account_type | VARCHAR(20) | 普通结算/金租监管 |
| project_id / leasing_org_id | UUID FK | 监管账户绑定项目+金租机构 |
| currency_code | VARCHAR(10) | |
| is_supervised | BOOLEAN | 是否监管账户 |

**supervised_rules** — 监管留存规则
| 字段 | 类型 | 说明 |
|------|------|------|
| account_id | UUID FK→bank_accounts | |
| min_retention_formula | VARCHAR(50) | 留存公式（默认：季度还款÷3，参数化） |
| current_min_retention | DECIMAL(18,2) | 当期最低留存额（随还款计划更新） |

**account_transfers** — 划转记录（监管→普通池）
| 字段 | 类型 | 说明 |
|------|------|------|
| from_account_id / to_account_id | UUID FK | |
| amount / transfer_date | DECIMAL / DATE | |
| approval_id | UUID FK→approvals | 划转必须走审批 |
| status | VARCHAR(20) | |

**capital_transactions** 加 `account_id UUID FK→bank_accounts` + `claim_status VARCHAR(20)`（待认领/已认领）：流水分账（普通/监管独立台账）+ 待认领款项池。

**核心逻辑**（`supervised_account_service.py`）：
- 月度最低留存额：默认 = 当期季度还款计划金额 ÷ 3；**非季度还款计划（按月/半年）的换算规则**（审计 A7）：当期最低留存额 = 未来 90 天应还本息总额 ÷ 3——统一"每季度资金储备均摊到月"的合规口径，公式在 supervised_rules 参数化
- 还款核销后自动更新下一期留存基准
- 监管账户到账 → 自动校验余额 vs 最低留存额 → 低于：补足预警；高于：提示可划转额度
- 划转发起 → approvals 审批 → 双方账户流水登记 → 独立台账留痕

**还款到期预警与逾期**（需求 3.7.3，审计 A11）：
- alert_service 新增规则：还款到期前 7/15 天推送，**联动校验监管账户余额**是否覆盖当期应还，不足触发资金补足预警
- `repayments` 加 `status`（逾期）+ `penalty_amount DECIMAL(18,2)` 罚息字段（罚息率入 leasing_rule_configs）

**收款管理**：收款登记区分入账账户（普通/监管）、待认领款项池（claim_status）、核销复用 payment_settlements（到单台）、核销自动算汇兑损益、监管账户收款后自动触发留存校验。

### 4.2 Week 3-4：收入确认管理 + 科目映射

> 科目映射与收入确认同期（凭证生成依赖映射表）。

**新增表**：

**revenue_recognitions** — 收入确认
| 字段 | 类型 | 说明 |
|------|------|------|
| project_id / contract_id | UUID FK | |
| batch_id | UUID FK→orders | 批次维度（可空，审计 A12） |
| device_id | UUID FK→devices | 单台维度（可空） |
| billing_id | UUID FK→billings | 可空（支持先确认后开票） |
| period_label / recognition_date | VARCHAR(20) / DATE | |
| amount | DECIMAL(18,2) | 不含税 |
| currency_code / booked_rate | | 外币折算，差异入汇兑损益 |
| revenue_method | VARCHAR(20) | 快照合同判定结果 |
| status | VARCHAR(20) | 草稿→已确认→已同步EBS |
| confirmed_by / confirmed_at | | 人工审核（走 approvals） |

**gl_account_mappings** — 科目映射
| 字段 | 类型 | 说明 |
|------|------|------|
| business_event | VARCHAR(50) | 收入确认/折旧计提/付款/收款/汇兑损益/金租放款/利息计提... |
| revenue_method | VARCHAR(20) | NULL=通用 |
| debit_account / credit_account | VARCHAR(50) | EBS 科目编码 |
| description_template | VARCHAR(200) | 凭证摘要模板 |

**核心逻辑**：
- 与开票/收款完全解耦（先开后确认、先确认后开均可）
- 设备点亮后按月自动生成确认草稿（基于 billings 不含税金额，单台粒度）
- 审核生效 → 按 gl_account_mappings 生成 Mock 凭证（应收/总账）→ ebs_sync_logs
- 收入成本配比：确认单关联同期间设备折旧、保险分摊、运维成本、融资成本（报表层做配比，确认单只挂金额）

**与 billings 的关系**：billings=应收计费（含税，面向客户对账）；revenue_recognitions=权责收入（不含税，面向核算）；billing_id 关联但不强制一一对应。

### 4.3 Week 5-6：对账中心完善（1 维 → 7 维）

| 维度 | 对账内容 | 差异标记 |
|------|---------|---------|
| 1. 销售全链路（扩） | 合同额 → 应收计费 → 已开票 → 已收款 → **已确认收入**；穿透至批次/单台 | 已开未收/已收未开/已确认未开等场景标红 |
| 2. 采购四单 | 采购合同 → 到货单 → 采购发票 → 付款单，**含预付款核销核对** | 金额差异/缺失环节 |
| 3. 资产交付 | 采购数量 → 到货数量 → 转固数量 → 点亮数量（单台计数） | 数量不一致 |
| 4. **监管账户** | 监管账户流水 vs 租金收入 vs 还款支出 vs 最低留存额合规性 | 留存不足/流水缺漏 |
| 5. 汇兑损益 | 发票汇率 → 结算汇率 → 损益入账（含设备分摊核对） | 折算差异 |
| 6. 业财一致性 | SIEGPU 业务数 vs EBS 财务数 | 应收/应付/资产/资金差异 |
| 7. 三流差异明细 | 全域合同/发票/资金对比 | 按客户/供应商/期间筛选 |

> ⚠️ Mock 局限：维度 6 在 Mock 下两端口径天然一致，本期验收标准 = 手动注入 3 条模拟差异验证展示/标红/定位管道；真实对账能力属期外里程碑（§0.3）。

### 4.4 Week 7-8：采购退货 + 合同终止（设备粒度）

**return_orders** — 退货单
| 字段 | 类型 | 说明 |
|------|------|------|
| project_id / original_order_id | UUID FK | |
| return_type | VARCHAR(30) | 到货不合格/压测不通过/合同终止 |
| status | VARCHAR(30) | 退货申请→出库确认→供应商收货→红字发票→退款核销/预付款冲回 |

**return_order_devices**（return_order_id / device_id / amount）——支持单台退货、批量退货。

**退货全链路**：
```
退货申请（单台/批量）→ 出库确认 → 供应商收货 → 红字发票(invoices direction=PAYABLE + reversal_of_id)
→ 供应商退款登记(capital_transactions IN) → 退款核销(payment_settlements)
财务联动：未转固→冲减在途物资；已转固→资产减少+折旧冲回（按台）；已付预付款→预付款追回待办
```

**合同终止结算**：销售终止→收入冲回+应收调整+资源释放（设备状态回退可用）；采购终止→应付调整+退货联动+预付款清算+供应商结算；均同步 EBS（Mock）。

### 4.5 Week 9-10：预算管控 + 经营看板

**project_budgets**（project_id / budget_type（采购/预付款额度/费用/融资额度） / budget_amount / used_amount / warning_threshold / active）

**预算校验**（service 拦截）：采购下单、预付款支付、付款申请、费用支出四类触发点；超预算→预警可继续；超 10%→硬拦截，需 approvals 审批预算调整（调整记录留痕）。

**Dashboard 升级**：
- 待办中心：预付款待付、监管账户余额预警、资金缺口预警、待还款、待投保、付款审批、预算超限
- 核心指标：当期合同额、累计回款、开票金额、确认收入、融资余额、资金池总余额、**监管账户余额**、设备交付进度
- **资金预测概览**：未来 3 个月余额预测 + 预付款需求 + 缺口提示（接 §4.6 引擎输出）
- EBS 同步状态卡片

### 4.6 Week 11-14：资金池预测引擎（核心新增）

**新增表**：

**cash_plan_items** — 资金计划项（预测统一数据源）
| 字段 | 类型 | 说明 |
|------|------|------|
| plan_type | VARCHAR(30) | 租金收入/融资放款/预付款退回/其他收入/采购预付款/采购付款/融资还款/运营费用/税费/保险费 |
| direction | VARCHAR(5) | IN/OUT |
| amount | DECIMAL(18,2) | |
| planned_date | DATE | 计划发生日 |
| account_type | VARCHAR(20) | 普通/监管 |
| source_type / source_id | VARCHAR(50) / UUID | 来源单据（billings/repayments/payment_requests/prepayments/leasing/insurance_policies/contracts/manual...） |
| status | VARCHAR(20) | 计划/已发生/已调整 |
| project_id / batch_id | UUID FK | 维度归集 |

**fund_forecasts** — 预测结果快照
| 字段 | 类型 | 说明 |
|------|------|------|
| scenario_name | VARCHAR(50) | 场景名（基准/场景A...，支持多场景对比） |
| period_type | VARCHAR(10) | 周/月/季 |
| params_json | JSONB | 场景参数覆盖层（采购批次/付款节奏/放款时间调整） |
| result_json | JSONB | 分期预测结果（期初/流入/流出/期末，普通池+监管分列） |
| created_by / created_at | | |

**计划项归集规则**（`cash_plan_service.py`，事件驱动 + 每日定时全量校准；审计 A5/A6 补全数据源）：

| plan_type | 数据源 |
|-----------|--------|
| 租金收入 | billings 生成时 |
| 融资放款 | leasing 放款计划 |
| 预付款退回 | prepayments 退回待办 |
| 其他收入 | **手工录入端点** |
| 采购预付款（未来需求） | **已签未执行采购合同（prepayment_ratio × 未下单金额）+ project_budgets 预付款额度——缺口测算的核心输入**（审计 A6） |
| 采购预付款（已审批） | prepayments 审批通过 |
| 采购付款 | payment_requests 审批通过 |
| 融资还款 | 还款计划生成时 |
| 运营费用 | **手工/周期性费用计划录入端点** |
| 税费 | **推导规则：销项按 billings.tax_amount、进项按已认证采购发票** |
| 保险费 | **insurance_policies 保费及摊销计划（二期产物，本周接管线）** |

> **监管留存锁定不做 plan_type**（审计 A22）：留存锁定不是现金流，作为预测引擎的独立扣减层——普通池可用余额 = 普通池期末余额 − 监管锁定额度（监管账户自身的预测单独列示）。

**预测引擎**（`fund_forecast_service.py`，纯函数核心 + 测试）：
- 按周/月/季生成预测表：期初余额、本期流入、本期流出、期末余额（普通池/监管账户分列 + 合并）
- 预付款缺口测算：未来批次预付款需求 vs 普通池可用余额 → 缺口为负触发融资预警
- 多场景模拟：参数覆盖层快照对比（不改基础计划项）
- 安全线阈值：期末余额低于安全线 → 首页预警
- 穿透：每期流入流出可下钻到计划项 → 来源单据
- **性能要求**：全量预测计算 ≤ 8 秒（十万级设备基数），计划项按 (period, account_type) 预聚合

### 4.7 三期交付物清单

| 类别 | 交付物 | 验收标准 |
|------|--------|---------|
| 数据模型 | **10 张新表**（bank_accounts、supervised_rules、account_transfers、revenue_recognitions、gl_account_mappings、return_orders、return_order_devices、project_budgets、cash_plan_items、fund_forecasts）+ 2 张表扩展（capital_transactions、repayments） | 迁移正常；测试全绿 |
| 后端 | 监管账户合规校验 + 收入确认 + 7 维对账 + 退货链路 + 预算拦截 + 预测引擎 | pytest 新增 ≥ 35 条；留存额/预测/分摊算法 100% + golden 算例 |
| 前端 | 监管账户页、收入确认页、对账中心重做、退货页、预算页、资金预测页 | 新增 8 条 e2e |
| 合规 | 监管账户独立台账、划转审批留痕 | 审计抽查可追溯 |

---

## 5. 四期：分析决策与系统完善（8-10 周）

> **目标**：经营决策数据支撑、资源池可视化、测算增强、权限治理
> **关键词**：全维度报表、资源池、测算工具、权限、操作说明、性能

### 5.1 Week 1-2：EBS 核算凭证 Mock 补全

- 凭证生成覆盖 6 类业务事件：收入确认、折旧计提、付款核销、汇兑损益、**金租放款/利息计提/长期负债**（V3.0 融资核算类接口）、预付款
- 融资核算类 Mock 接口：放款单、还款计划、利息计提、长期负债凭证（项目/批次级）
- 资金类接口含监管账户流水（流水级）；采购应付类补 `sync_goods_receipt`（采购入库）真实触发点接管线

### 5.2 Week 3-4：全维度报表 + 项目全景视图

**项目全景视图**（`ProjectOverview.vue`）：三级穿透（项目→批次→单台），聚合采购/销售合同、设备交付进度、资产清单、融资明细、**监管账户余额**、收付款、收入确认、成本归集、累计毛利、**资金预测结果**。

**报表矩阵**（`report_service.py`）：
| 报表 | 维度 | 关键指标 |
|------|------|---------|
| 合同毛利明细表 | 单合同，穿透批次/单台 | 收入/成本/毛利额/毛利率 |
| 项目全周期毛利表 | 项目 | 总收入/全成本/毛利/净利率/IRR/回收期 |
| 项目年度毛利表 | 项目×年度 | 收入/成本/毛利，预算vs实际 |
| 采购付款统计表 | 供应商 | 合同额/已付/应付余额/账龄 |
| **预付款台账报表** | 项目×金租模式 | 预付款余额、退回/结转进度 |
| 设备状态明细表 / 资产转固明细表 | 批次/项目 | 单台粒度 |
| **单台设备全成本表** | 单台 | 采购+运输+保险+折旧+融资利息全成本 |
| 资源利用率报表 | 型号×项目 | 占用率 |
| 融资余额表 / 还款计划表 / 资金成本分析表 | 融资项目 | 放款/已还/剩余/下期应付 |
| **监管账户报表** | 监管账户 | 余额表、最低留存额执行表、划转明细表 |
| **资金预测报表** | 周/月/季 | 预测表、缺口测算表、多场景对比表 |
| **资金来源构成分析表** | 资金池 | 自有/流贷/金租放款占比（需求 3.7.6） |
| 汇兑损益明细表 | 币种×项目 | 当期发生额 |
| 核算审计报表 | 核算路径 | 总额法/净额法/经营租赁拆分 + **保险台账表 + 合同变更终止统计表 + 操作日志审计表** |

### 5.3 Week 5-6：资源池 + 测算增强

**资源池**（`ResourcePool.vue`，设备级）：在途/压测/可用/已占用实时计数；上架→可用，点亮→已占用；权属标记（自购表内/金租表外/转售表外）；型号/批次/项目筛选。
> **表外资源占用来源**：转售业务不走设备层，由销售合同生效时登记"表外资源占用"（新增 `resource_occupations` 轻量表：合同/客户/资源量/期间），终止释放。

**资金成本测算工具**（`FundingCalculator.vue`）：
- 参数：融资金额、年利率、期限、放款日、手续费率、还款周期（按月/按季——`utils/repayment_plan.py` 已支持月/季/半年，工具直接暴露参数，无需改引擎）
- 等额本金/本息切换实时重算；输出全周期还款计划 + **每期月度最低留存额** + 实际年化利率（含手续费）
- **监管账户资金占用成本**测算纳入综合资金成本
- 支持**按批次/按设备放款拆分**测算，自动汇总项目综合融资成本
- 一键同步融资项目台账 + **资金预测模型**（生成计划项）

**利润测算增强**：`params_json` 加运输费/保险费/运维/电费/带宽/税费率/折现率/残值率/**预付款比例/资金占用成本**；年度拆分；**单台残值**（按设备设残值率与处置费率汇总）；预算vs实际自动对比；定稿版本一键同步立项基准（沿用现有多版本同步能力，本周复核口径）。

### 5.4 Week 7-8：权限治理 + 操作说明 + 收尾

**权限治理**：
- 全端点接入 `require_role()`（83 个端点逐模块收紧，默认先放行现有角色避免回归）
- 数据权限：按项目 + 部门隔离；**资金操作、监管账户操作、财务核算操作单独授权**（V3.0 5.3）
- 安全：login_logs（IP/时间/成败）、连续失败 5 次锁 30 分钟、密码策略（≥8 位含大小写+数字）、**关键数据加密存储**（银行账号等敏感字段，复用 §4.1 bank_accounts 加密方案）
- 敏感操作双重审计：红冲、收入判定覆盖、预算调整、**监管划转、预付款调整**
- 数据留存策略：单据/附件/日志保留期限配置（合规第六章）

**资产处置报废**（需求 3.8.1 补齐）：处置/报废登记 → 资产 operation_status→已处置 + 折旧截断（复用售后回租出售路径）→ EBS FA 资产减少同步（Mock）。

**操作说明中心**（`HelpCenter.vue`）：分模块指南、业务勾稽关系图（项目-批次-单台-采购-资产-合同-融资-资金-财务）、**金租专项说明（直租/回租差异、监管账户规则、预付款流程）**、EBS 对接规则。

**批量导入导出扩展**：在现有 excel_service（suppliers/customers/capital_transactions）基础上扩至 devices、contracts、付款、发票（V3.0 5.5）。

**性能验证**：
- **十万级设备**数据下：设备清单查询 ≤5 秒、资金预测计算 ≤8 秒；**百万级单据**下报表生成 ≤10 秒（V3.0 5.1 双口径）
- 50 并发压测（Locust）；前端 Lighthouse；设备相关查询索引评审（devices.sn、device_stages.(device_id,stage)、payment_settlements 复合索引）

### 5.5 四期交付物清单

| 类别 | 交付物 | 验收标准 |
|------|--------|---------|
| 数据模型 | **2 张新表**（resource_occupations、login_logs） | 迁移正常 |
| EBS Mock | 核算凭证 6 类事件 + 融资核算类接口 + 采购入库触发 | 全覆盖 |
| 报表 | 14 类报表 + 项目全景三级穿透 | 与 Excel 对账基准一致（庭宇1372台测算.xlsx 现金流 sheet） |
| 前端 | 资源池、测算工具、操作说明中心 | e2e 覆盖 |
| 权限 | 全端点 RBAC + 数据权限 + 资金单独授权 | 越权返 403 |
| 性能 | 压测报告 | 10 万设备 / 百万单据 / 50 并发 / 预测≤8s / 报表≤10s |

---

## 6. 技术策略

### 6.1 双轨兼容架构（一期核心决策，审计 A3/A20 修订）

```
                    order_service.resolve_flow_type(order)
                    （首次判定后固化于 orders.flow_type，只升不降）
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
 旧路径（批次粒度）     新路径（设备粒度）      转售路径（无实物交付）
 orders+delivery_stages  devices+device_stages   无 devices、无交付节点
 6节点、点亮建卡起折旧   7节点、上架建卡/点亮起折旧 billings 由销售合同
 ── 保留原代码           ── 新代码                收款计划/手工驱动
```

- **三条防护纪律**：① is_batch 订单不建 delivery_stages；② 旧触发入口（light_on/generate_billing/公开端点）强制过闸，设备粒度订单直接拒绝；③ 批次聚合状态写 orders.batch_status 独立字段
- 转售项目（净额法、表外资源）无实物交付，计费不走点亮节点（审计 A20）
- 存量项目自然结项后旧路径下线（四期后评估）

### 6.2 EBS Mock 架构

业务层 → `ebs_sync_service`（写日志 → 调 client → 更新日志）→ `ebs_client`（Mock/真实由 `EBS_MOCK_MODE` 切换）。切换真实 EBS 需：提前获取接口规范、按规范定义 `EbsResponse` 适配器、按真实错误码校准 retry/失败语义；日志表、映射表、业务调用方式不变。`entity_version` hash 为真实对接后的幂等/乱序处理预留。

### 6.3 数据库迁移策略

- 新表一律 Alembic 新版本；现有表加字段 `ADD COLUMN ... DEFAULT ...`（向后兼容）
- **assets 结构改造 + billings 唯一索引迁移**是仅有的两处破坏性变更：独立迁移脚本 + 迁移前后总额校验 + 可回滚
- orders 批次行放宽 NOT NULL：迁移脚本处理（存量行不受影响，仅约束放宽）
- 每期迁移独立执行、可回滚

### 6.4 测试策略

- 现有 94 pytest + 24 e2e **每期结束全绿**（硬性门禁）
- 新功能单元测试 ≥ 80%；纯算法（判定/汇兑/分摊/留存额/预测）100% + golden 算例
- e2e 每期新增 4-8 条关键路径；双轨路径各至少 1 条 + 双计防护专项（同批设备不产生重复资产/账单）
- EBS Mock 模式全覆盖

### 6.5 前端策略

Vue 3 + Naive UI + Pinia 不变；通用 CRUD 走 `GenericCrud.vue` + `modules.ts`；复杂页面独立开发（对账中心、资源池、资金预测、测算工具）；设计系统沿用 `design-system/MASTER.md`。

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 设备层重构波及面超预期 | 中 | 高 | 一期只做地基不做新功能；判定点唯一化；94 测试门禁；双轨可回退 |
| 双轨双计（资产/账单重复） | 中 | 高 | §6.1 三条纪律 + 双计防护专项测试 |
| assets 拆分迁移数据不一致 | 中 | 高 | 迁移前后总额/折旧校验脚本；当前为测试数据量小；生产切换前全量备份 |
| 转租赁核算规则（R1b） | 已裁定 | — | 财务 2026-08-04 裁定：服务费按月确认（§3.2 R1b）；若日后成本侧改按新租赁准则拆分，仅调整 gl_account_mappings 配置，不改引擎 |
| EBS 接口规范/测试环境延迟 | 中 | 高 | 二期 W1 即申请；Mock 按规范写适配器；入站为期外里程碑不影响本期验收 |
| 监管留存规则与金租合同实际条款偏差 | 中 | 中 | 留存公式参数化（supervised_rules），含非季度还款换算规则 |
| 资金预测数据源不全（费用/税费手工项维护缺失） | 中 | 中 | 手工录入端点 + 每日全量校准 + Dashboard 数据完备性提示 |
| 资金预测性能（10 万设备） | 中 | 中 | 计划项预聚合 + 快照；四期压测门禁 ≤8s |
| 收入判定规则与业务偏差 | 中 | 高 | 纯函数规则易调；人工覆盖入口 + 审计留痕 |
| 币种改造波及面 | 中 | 中 | 字段默认 CNY 渐进改造；历史数据人民币口径不变 |
| 全端点 RBAC 回归 | 中 | 中 | 先默认放行再逐模块收紧；每模块接入同步更新 e2e |
| 存量数据与新字段语义混用 | 中 | 中 | 新字段一律 DEFAULT；历史报表按旧口径不强制对齐 |

---

## 8. 路线图总览

```
Month 1-2         Month 3-5           Month 6-8           Month 9-11         Month 12
│ 一期 8-10周      │ 二期 12-14周       │ 三期 12-14周       │ 四期 8-10周       │
│                 │                   │                   │                  │
│ devices 层  ██  │ EBS Mock 骨架 ██  │ 监管账户     ██   │ EBS 凭证补全  █  │
│ 节点设备化  ██  │ 收入判定     ██   │ 收入确认+科目 ██  │ 全维度报表    ██ │
│ 一机一卡    ██  │ 币种汇率     ██   │ 7维对账      ██   │ 资源池+测算   ██ │
│ 金租双模式  ██  │ 保险管理     ██   │ 退货+预算    ██   │ 权限+收尾     ██ │
│ 联调回归    ██  │ 合同+预付款  ██   │ 资金预测     ████ │                  │
│                 │ 付款+审批    ██   │                   │                  │
▼ 一期验收        ▼ 二期验收          ▼ 三期验收          ▼ 四期验收（Mock 全量）
                                                              │
                                                              ▼ 期外：真实 EBS 对接
```

---

## 9. 附录：现有资产清单（不改动部分）

| 模块 | 文件 | 原因 |
|------|------|------|
| 资金池核心 | `capital_service.py`, `capital_transactions`, `capital_allocations` | 稳定运行，算法已验证（仅加 account_id/币种/claim_status 字段） |
| 金租流程 | `leasing_service.py`, `leasing_processes`, `leasing_nodes` | 9 节点流程已完备（仅加模式字段） |
| 计费 | `billing_service.py`, `utils/billing.py` | 首月按天折算公式正确（起点改按台 + 唯一索引迁移 + 服务层校验改设备维度） |
| 折旧 | `utils/depreciation.py` | 5 年直线+残值 10%+末期吸收尾差（公式不动，对象改单台） |
| 还款计划 | `utils/repayment_plan.py` | 等额本息/本金，**已支持月/季/半年**（四期测算工具暴露参数即可） |
| 审计 | `core/audit.py`, `audit_logs`, `step_audit_logs` | 17 种 action 覆盖全面 |
| 预警 | `alert_service.py` | 8 条规则运行正常（新增续保/还款到期规则） |
| 向导工作台 | `workflow_service.py`, `ProjectWorkspace.vue` | 表驱动通用引擎（一期新增设备粒度模板，旧模板不动） |
| OCR | `ocr_service.py` | 增值税发票识别可用 |
| 设计系统 | `design-system/MASTER.md`, `tokens.css` | 视觉规范不变 |

> **例外**：`orders` / `delivery_stages` / `assets` / `billings`（唯一索引）四张表按 §0.5 评审结论做结构演进（双轨保护旧路径）。

---

## 10. 版本与审计记录

### 10.1 改造 vs 重做决策记录（V2.0 关键决策）

V3.0 需求评审时评估了"重做系统"选项，结论为**改造**，依据：
- 被设备粒度推翻的代码约占后端 15-25%，未达重做临界线（经验值 60-70%）
- 核心算法（资金池/计费/折旧/还款）已验证且有 94 测试兜底，重做需 12-16 周重新发明且质量未必复位
- 四大新域无论重做与否都是纯新增，成本相同
- 技术栈（FastAPI + Vue 3）与需求无架构性冲突，差距在数据模型粒度而非架构

### 10.2 V1.0 → V1.1 审计修订记录

独立审计发现 0 CRITICAL / 3 HIGH / 10 MEDIUM / 9 LOW，已全部处置：W1 收入确认补排期（HIGH）；W7 摘要分期错误（HIGH）；W12 EBS 切换声明收敛（HIGH）；W8/W9/W10/W13/W14/W16/W17（MEDIUM）与 W2-W6/W11/W15/W18-W22（LOW）已在对应章节处置。

### 10.3 V1.1 → V2.0 修订记录（V3.0 需求适配 + 两轮人工审阅）

| 编号 | 问题 | 处置 |
|------|------|------|
| V2-1~5 | V3.0 四新域 + 预付款全缺失 | 新增一期地基重构（§2）、金租双模式（§2.4）、监管账户（§4.1）、资金预测（§4.6）、预付款（§3.5） |
| V2-6~8 | 汇兑损益缺 invoice_rate / 核销缺分配表 / 无审批流 | §3.3 补汇率字段；§3.6 payment_settlements + approvals |
| V2-9~12 | R1 输入缺失 / 转固折旧状态机 / 保费原值冲突 / 科目映射排期 | §2.1 项目字段；§2.3 operation_status；§3.4 点亮前窗口约束；§4.2 映射与收入确认同期 |
| V2-13~18 | 折旧描述错误 / 银行账户排期 / 对账维度 / 审计报表 / 待认领 / 表外占用来源 | 各对应章节修正 |
| V2-19 | ~~还款计划仅按月~~ **记录错误，V2.1 已更正（见 A7）** | — |
| V2-20~22 | 性能口径 / ebs 幂等字段 / 散项落点 | §5.4 / §3.1 entity_version / 散项包 |

### 10.4 V2.0 → V2.1 独立审计记录（1 CRITICAL + 6 HIGH + 9 MEDIUM + 8 LOW 全部处置）

独立审计（对抗性复审，2026-08-04）发现 24 项，另纠正事实性错误 2 处（按季还款已存在；billings 有唯一索引且金额仅来自合同级 monthly_rent）：

| 编号 | 问题 | 级别 | 处置 |
|------|------|------|------|
| A1 | 按台计费撞 billings 唯一索引 + 单台金额来源未定义 | CRITICAL | §0.5/§2.3：索引迁移 (device_id,period_index) + 服务层校验改设备维度 + devices.monthly_price 快照机制 |
| A2 | 工作台模板硬编码旧路径，新项目向导卡死 | HIGH | §2.2：新增 device-flow-7stage 模板 + _TABLE_CLASSES 登记 + 列入一期交付物 |
| A3 | 批次聚合点亮与旧触发器双计风险 | HIGH | §2.2/§6.1：三条纪律（is_batch 不建旧节点/旧入口强制过闸/聚合状态独立字段）+ 双计防护测试 |
| A4 | 批次载体 orders 的 NOT NULL 冲突 + is_batch 未入字段清单 + flow_type 判定中间态翻转 | HIGH | §2.1：orders 入扩展清单（7 张）+ 批次行放宽约束 + flow_type 固化只升不降 |
| A5 | 资金预测三类 plan_type 无数据源 | HIGH | §4.6：归集规则表补手工费用/税费推导/保险费管线 |
| A6 | 预付款缺口测算缺"未来需求"输入 | HIGH | §4.6：已签未执行合同×prepayment_ratio + 预算额度生成计划级需求项 |
| A7 | V2-19 事实错误：按季还款已存在；真缺口是非季度留存换算 | MEDIUM | §4.1 补 90 天应还÷3 换算规则；§5.3 删按季扩展项；§10.3 V2-19 标记更正 |
| A8 | SN 规则一期用、编号规则表二期建 | MEDIUM | §2.1 一期硬编码 + §3.6 回迁 |
| A9 | 到货验收单/暂估入库/EBS 入库接口缺失 | MEDIUM | §2.2 节点动作 + §3.1/§5.1 sync_goods_receipt |
| A10 | 进项税独立核算/认证/抵扣缺失 | MEDIUM | §1.2 P1 新增 #21 + §3.6 certification_status + 进项税台账 |
| A11 | 到期预警/逾期罚息无落点 | MEDIUM | §4.1：alert 规则 + repayments 逾期/罚息字段 |
| A12 | revenue_recognitions 缺 batch_id | MEDIUM | §4.2 补字段 |
| A13 | 设备→销售合同绑定无字段 | MEDIUM | §2.1 devices.sales_contract_id（与 A1 同根） |
| A14 | EBS 入站排除在计划外但未声明期外 | MEDIUM | §0.3 期外里程碑声明 |
| A15 | 立项多级审核/项目号强制未承接 | MEDIUM | §3.6：approvals.biz_type 加项目立项 + schemas 层 project_id 非空校验 |
| A16 | settlements/prepayments 字段撑不起声明场景 | MEDIUM | §3.6：invoice_id 可空 + batch_id 维度 + prepayments.settled_amount |
| A17 | 备查台账撞 assets NOT NULL 折旧字段和 UNIQUE | MEDIUM | §2.1/§2.3：off_balance_registers 独立表 |
| A18 | 销售侧变更联动缺失 | LOW | §3.5 补销售分支 |
| A19 | 保费摊销/续保/理赔无承接 | LOW | §3.4：amortization_months + claims JSONB + alert 续保规则 + 摊销接预测管线 |
| A20 | 转售计费路径未定义 | LOW | §6.1 第三分支（合同收款计划驱动） |
| A21 | 计数/口径不一致若干 | LOW | §1.2 P1/P2 计数、§2.6、§3.7、§4.6 fund_forecasts 字段、§5.5 数据模型行 全部对齐 |
| A22 | 监管留存锁定混入 plan_type 扭曲口径 | LOW | §4.6：独立扣减层 |
| A23 | 需求散项漏网 9 项 | LOW | §1.2 散项落点包 + 各章节落点 |
| A24 | devices.status 与 device_stages 双写规则未定义 | LOW | §2.1：物化列 + 状态机单点维护 |

### 10.5 V2.1 → V2.2 修订记录（财务裁定落地）

- **R1b 转租赁核算路径财务裁定（2026-08-04）**：直租/售后回租项目对外出租，收客户租金**全额按服务费逐月确认收入**；不走经营租赁/融资租赁转租赁口径。判定引擎 R1b 从"待财务确认"改为自动判定"服务费（按月确认）"；`revenue_method` 枚举增加"服务费"。我方付金租的租金按月进成本，收入成本同期配比。
- 连带更新：§3.2 规则库、§7 风险表（该风险已消除）、§0 版本头。

> **文档版本**：V2.2 | **编写日期**：2026-08-04 | **审计日期**：2026-08-04
> **需求来源**：财务团队《SIEGPU ERP系统需求说明书 V3.0》（`doubao-requirements-v3.md`）
> **下一状态**：用户评审 → 排期执行
