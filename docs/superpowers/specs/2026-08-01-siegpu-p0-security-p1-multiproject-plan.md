# SIEGPU 审计留痕 + 多项目并行管理 — 项目计划书 v1.1

> 日期：2026-08-01 | 状态：v1.1（按用户决策重构）
> 依赖：[v3.1 全链路设计](./2026-08-01-siegpu-erp-design-v3.md)、[向导工作台设计 v1.2](./2026-08-01-siegpu-wizard-workflow-design.md)、[易用性评估](./2026-08-01-siegpu-usability-evaluation.md)
> 现状基线：pytest 79 全绿 / e2e 28 全绿 / vue-tsc 0 错误
> v1.0 → v1.1 变更：**权限管理（C3）整体暂缓**（用户 2026-08-01 决策），成果保留在 §7 备启；审计日志（C4）保留在近期——零用户影响、纯留痕；P1 提前为主线

---

## 0. 决策记录（用户已拍板）

| # | 决策 | 结论 |
|---|---|---|
| 1 | 权限管理（端点角色管控、§3 矩阵、前端守卫、403 e2e） | **暂缓，放到后面做**；§7 成果保留，启动时无需重新设计 |
| 2 | Step 10 金租放款自审批 | 维持 FINANCE_DIRECTOR 执行 |
| 3 | P1.5 最小审批流（放款/红冲/强制完成） | 单独立项，不在本期 |
| 4 | 删除操作收紧到 ADMIN | 认可"不过激"，随权限管理一并暂缓生效 |

---

## 1. 背景与问题定义

### 1.1 审计留痕（v3.1 审计 C4，本期实施）

`AuditLog` 模型存在（`models/user.py:22`）、表存在（schema.sql:372），但**全项目零写入**——放款/红冲/核销/验收/置换/调配全无痕，出问题无法追溯。向导操作已有 StepAuditLog，缺口在业务操作。修复对用户完全无感（不新增 403、不改任何操作路径），纯增益。

### 1.2 多项目并行管理（本期主线）

单项目 18 步全链路已通，但实际业务是财务同时推进 3-5 个项目。缺口：资金池无项目拆分视图、无项目对比、无到期/逾期主动预警。

### 1.3 目标

- 审计：敏感业务操作全部留痕（人、动作、对象、金额、时间）
- P1：财务一屏看清"哪个项目钱闲、哪个项目缺钱、哪个项目回款慢、哪笔还款逾期"，并能直接发起调配

---

## 2. 审计日志写入（C4）

### 2.1 实施

- 新增 `app/services/audit_service.py`：`log(db, user, action, target_type, target_id, before=None, after=None)`，各 service 事务内调用（与业务记录同事务提交，原子）
- `user_id` 由 endpoint 层透传 `get_current_user`（service 签名加 `actor: User` 参数，逐一改调用点，全量 grep 防遗漏）

### 2.2 写入动作清单（v3.1 §7 为基座 + 本期补充）

| action | 触发点 | 关键字段 |
|---|---|---|
| ACCEPT_APPROVE | 验收通过/驳回 | target=acceptance_id, after=status |
| SUPERSEDE | 金租放款触发置换 | target=funding_replacement_id, after=置换金额 |
| DISBURSE | 金租放款 | target=leasing_process_id, after=放款金额/期数 |
| RECONCILE | 发票核销 | target=invoice_id, after=核销金额 |
| REVERSE | 红冲（发票/流水） | target=原记录 id |
| ALLOCATE / ALLOCATE_RETURN | 资金调配/归还 | target=allocation_id, after=金额 |
| CONFIRM_UPLOAD | 客户确认单上传 | target=confirmation_id |
| CAPITAL_TXN | 资金记账（补留痕） | target=transaction_id, after=金额/方向 |
| LIGHT_ON | 点亮 | target=order_id |
| SKIP_STEP / FORCE_DONE | 工作台跳过/强制完成 | 已由 StepAuditLog 覆盖，不重复写 |

### 2.3 迁移要求（v3.1 §7 已预警）

- `audit_logs.action` CHECK（schema.sql:375）现仅含 `CREATE/UPDATE/DELETE/REVERSE/LOGIN/APPROVE_OVERCONTRACT/SUPERSEDE`，必须扩入新 action，否则 PG 拒绝写入
- **双同步**：Alembic 0004 迁移 + schema.sql 同步改（测试库走 schema.sql 不走 alembic——v3.1 审计 H4 的教训）

### 2.4 同批小安全项（不涉及权限管控）

| # | 项 | 现状 | 修法 |
|---|---|---|---|
| S1 | seed 密码硬编码 | `seed.py:12 PASSWORD = "sie123"` 且写进手册 | 改 `os.getenv("SEED_PASSWORD", "sie123")`；手册注明生产部署必须设该变量；e2e specs 同步读 env |
| S2 | 前端双端口映射 | docker-compose 同时映射 9000 与 8080 | 收敛到一个端口，e2e baseURL 统一 |
| S3 | e2e 残留数据 | DB 内 `E2E-向导-*` 测试项目与被污染的 workflow 实例 | 清理脚本 + spec 改用完即删 |

---

## 3. P1：多项目并行管理

### 3.1 前置小债（先做，均为已知缺口）

| # | 项 | 内容 |
|---|---|---|
| D1 | `GET /api/capital/allocations` | 后端补调配列表接口；前端"归还"去掉 localStorage hack，改读接口 |
| D2 | `InvoiceOut.matched_amount` | 后端暴露已核销累计金额；前端核销弹窗显示精确进度 |
| D3 | 建项目开放 `template_id` | projects 创建接口+表单加流程模板下拉（18 步/15 步），多项目路径分化的前提 |

### 3.2 资金池项目视图（核心交付）

- 后端 `GET /api/capital/pool-by-project`：按项目返回 净头寸 / 可调余额 / 在途调配（借出未还）/ 近 30 天收支
- 前端资金池页新增"分项目"Tab：表格 + 闲置/缺口标识（净头寸>阈值标"可调出"、<0 标"缺口"），行内直接发起「调配」
- 公司级总余额保留在顶部

### 3.3 项目组合总览

- 后端 `GET /api/workflows/portfolio`：每项目 current_step/状态/当前步待办角色/停滞天数（updated_at 推算）
- Dashboard 或独立页："项目 × 阶段 × 当前步"网格，点击进工作台——多项目管理的入口页

### 3.4 项目对比

- 后端 `GET /api/reports/project-comparison`：IRR/NPV（profit_scenarios 已存）、回款率（已收/应收）、逾期笔数、工作流进度%
- 前端对比表，列可排序

### 3.5 预警规则（挂现有应用内告警卡片，不新造通道）

| 规则 | 数据源 | 阈值（默认） |
|---|---|---|
| 金租还款逾期 | repayment 计划 due_date < 今天且未确认 | 逾期即报 |
| 交付阶段卡住 | delivery_stages / leasing nodes stuck 或未动 | >7 天 |
| 合同到期 | contracts.end_date | <30 天 |
| 工作流停滞 | project_workflows.updated_at | >14 天 |

---

## 4. 实施计划（7 个 Phase，约 7.5 天）

| Phase | 内容 | 工时 | 交付物 |
|---|---|---|---|
| 1 | 审计日志写入 + CHECK 迁移（alembic+schema.sql 双同步）+ 小安全项 S1-S3 | 1.5d | 敏感操作全留痕 |
| 2 | P1 前置 D1-D3 | 1d | 三笔小债清零 |
| 3 | 资金池项目视图 | 2d | 分项目 Tab + 行内调配 |
| 4 | 项目组合总览 | 1d | 进度网格页 |
| 5 | 项目对比 | 1.5d | 对比表 |
| 6 | 预警规则 ×4 | 1d | 告警卡片生效 |
| 7 | 手册更新 + 回归终验 | 0.5d | 文档同步、全绿收官 |

---

## 5. 测试策略

- **pytest 新增约 10 条**：审计写入断言（每类操作后 audit_logs 有对应行）、CHECK 迁移后新 action 可写、allocations 列表、matched_amount、pool-by-project 数值正确性、portfolio/comparison 端点
- **e2e 新增约 6 条**：分项目资金视图与行内调配、组合总览网格、预警出现、建项目选模板
- **回归基线**：现有 pytest 79 + e2e 28 必须全绿；S1 改 env 密码后 e2e specs 同步改读 env（当前硬编码 sie123）

---

## 6. 风险与缓解

| # | 风险 | 级别 | 缓解 |
|---|---|---|---|
| 1 | CHECK 约束迁移在存量 DB 失败 | MEDIUM | alembic 迁移含 downgrade；先在测试库验证；schema.sql 双同步防测试库漂移 |
| 2 | service 加 actor 参数改调用点遗漏 | MEDIUM | 全量 grep 调用点清单化；pytest 覆盖的 service 路径会立刻暴露 |
| 3 | 权限暂缓期间误操作风险敞口仍在 | MEDIUM | 审计留痕先行（本计划 §2），事后可追溯；内部系统+账号可控，风险可接受；§7 备启包随时可启动 |
| 4 | seed 密码改 env 后 e2e/部署断 | LOW | docker-compose 补默认 env；手册同步；e2e 读 env |

---

## 7. 暂缓备启包：权限管理（C3，v1.0 §2/§3 成果保留）

> 以下内容已按 v3.1 §6 设计完毕，启动时直接实施，无需重新设计。包含三块：

**A. 后端权限落地**：按下方矩阵给全部业务端点挂 `Depends(require_role(...))`（路由级）；A 类动作 service 层二次校验角色；读操作全员登录即可不收紧。预估 1.5d（含 pytest 403 用例）。

**B. 前端收编**：路由守卫 + 侧边栏按角色过滤 + 按钮显隐收尾（v3.1 §6 要求③，易用性评估 O2 遗留）。预估 0.5d。

**C. 403 e2e 回归矩阵**：敏感端点 × 角色 × 期望结果，防权限静默退化。预估 0.5d。

### 权限矩阵（已确认默认值，启动时最后过一遍即可）

> 基座为 v3.1 §6，补全其未覆盖的存量端点。V=查看 C=新增 E=编辑 D=删除 A=审批/执行高危动作。·=无权限（403）。读操作一律全员 V，下表只列写权限。

| 模块/操作 | ADMIN | FINANCE_DIRECTOR | FINANCE_STAFF | PROCUREMENT | DELIVERY |
|---|---|---|---|---|---|
| 主数据（客户/供应商/设备/银行）C/E | CE | · | · | CE | · |
| 主数据 D | D | · | · | · | · |
| 项目 C/E | CE | · | · | CE | · |
| 合同 C/E | CE | · | · | CE | · |
| 合同/订单等一切删除 | D | · | · | · | · |
| 采购订单 C/E | CE | · | · | CE | · |
| 点亮上线 | E | · | · | E | · |
| 交付阶段推进 | E | · | · | E | E |
| 销售订单 C/E | CE | CE | · | · | · |
| 资金记账（入金/出金） | C | C | C | · | · |
| 资金调配/归还 | C | C | · | · | · |
| 流水红冲 | A | A | · | · | · |
| 金租申请创建/节点推进 | CE | · | · | · | CE |
| 金租放款（含自动置换） | A | A | · | · | · |
| 还款确认 | E | E | E | · | · |
| 验收创建 | C | C | · | C（采购验收） | C（销售验收） |
| 验收通过/驳回 | A | A | · | · | · |
| 客户确认单上传 | C | C | · | · | C |
| 客户确认/争议 | E | E | E | · | · |
| 计费生成 | C | C | C | · | · |
| 开票/收款登记 | C | C | C | · | · |
| 发票核销 | E | E | E | · | · |
| 发票红冲 | A | A | · | · | · |
| 盈利测算保存场景 | C | C | C | · | · |
| 文件上传 | 跟随所属实体写权限 | | | | |
| 报表/工作台/待办 查看 | V | V | V | V | V |
| 跳过必做步骤/手动完成（已实施） | A | A | · | · | · |
| 模板管理（已实施） | CE | · | · | · | · |

**与 v3.1 §6 的差异说明**：①发票核销 v3.1 为"FINANCE_STAFF 发起待 A"，因审批流不存在，放行 FINANCE_STAFF 直接执行，P1.5 再引入审批；②主数据/项目/合同/订单的存量写权限为本次新增定义，默认给 PROCUREMENT；③删除一律收紧到 ADMIN（用户已认可）。

### 非目标（权限启动时也不做）

- 完整 BPM/通用审批引擎（P1.5 单独立项）
- 用户管理 UI、邮件/企业微信通知通道
- 审计日志查看 UI（只保证写入留痕，查看页后续单独立项）

---

> **下一步**：按 Phase 1（审计留痕 + 小安全项）动工。
