# 复审报告 — SIEGPU ERP 设计书 v2.0

> 复审对象：`2026-07-30-siegpu-erp-design-v2.md`（v2.0，含复审修订前）
> 复审日期：2026-07-30
> 复审方式：独立 `code-reviewer` agent 第二轮复审（逐条核验 v1.0 审计项 + 6 维度找新问题 + DDL/SQL/公式逐项验算）
> 复审结论：**新引入 FAIL 6 / WARNING 16；v1.0 审计项 RESOLVED 19 / PARTIAL 3 / OPEN 0 — v2.0 不可直接进入开发，需修 6 FAIL**

---

## 复审对象

- v2.0 设计书：`2026-07-30-siegpu-erp-design-v2.md`
- v1.0 审计报告：`AUDIT-2026-07-30-siegpu-erp-design-v1.md`
- v1.0 原文：`2026-07-30-siegpu-erp-design.md`

> 计数差提醒：v1.0 审计抬头"FAIL 6 / WARNING 24（合计 30）"，实际问题清单表为 24 行（FAIL 1–6 + WARNING 7–24 = 6+18）。下方按 24 行逐条核验。此为 v1.0 审计自身计数瑕疵，非 v2.0 问题。

---

## 第一部分：v1.0 审计项核验（24 行逐条）

| # | 级别 | v1.0 问题 | v2.0 处置 | 判定 |
|---|---|---|---|---|
| 1 | FAIL | 无 billing/收入确认表 | 新增 `billings` + 三流勾稽 | RESOLVED |
| 2 | FAIL | 无 users 表、外键悬空 | 新增 `users`，补齐 created_by/approved_by/owner_id | RESOLVED |
| 3 | FAIL | 放款/调配/点亮无幂等事务 | idempotency_keys + 头 + 业务去重 + 事务 | PARTIAL（调配两流水键冲突，见 NF1） |
| 4 | FAIL | 软删除与红冲缺失 | 全表 deleted_at + reversal_of_id + 金额禁硬改 | PARTIAL（红冲外键仅 capital_transactions，见 NF4/NW4） |
| 5 | FAIL | audit_logs 放二期 | 前移一期 + 运维 + 仅总监可读 | RESOLVED |
| 6 | FAIL | 无测试策略 | §8 分层 + 80% + DoD + Excel 对账基准 | RESOLVED |
| 7 | W | 数据录错回溯风险 | 风险表 + 红冲 | RESOLVED |
| 8 | W | direction 中英文混用 | 资金 IN/OUT；票据 RECEIVABLE/PAYABLE | RESOLVED |
| 9 | W | 时间戳不统一 | 通用列 + 触发器 | RESOLVED |
| 10 | W | rate 单位歧义 | NUMERIC(10,8) 小数 + 附录 B 对照表 | RESOLVED |
| 11 | W | 状态枚举无 CHECK/流转 | CHECK + §3.5 迁移表 + assert_transition | RESOLVED |
| 12 | W | 发票与流水无 FK | invoices/billings.capital_transaction_id | RESOLVED |
| 13 | W | 还款手录 + leasing 缺字段 | 加利率/期数/频率/方式；放款自动生成 | RESOLVED |
| 14 | W | tax 无 tax_rate/含税口径 | 含税/不含税/税额/税率齐备 | RESOLVED |
| 15 | W | 折旧部分年份 + end_date | 月折旧 + 首末月 + end_date=点亮+5年 | RESOLVED |
| 16 | W | "13 张"声明错误 | 改 19 张（分域小计有误，见 NW12） | RESOLVED |
| 17 | W | 调配 vs 可调余额无校验 | 加公式 + 422 | PARTIAL（公式重复扣减，见 NF5） |
| 18 | W | 发票超开无拦截 | 录入校验 + 总监审批 | RESOLVED |
| 19 | W | 申请额 vs 实际放款无对账 | actual_disbursement_amount + 预警 | RESOLVED |
| 20 | W | 点亮→资产→折旧含糊 | 同事务点亮→建资产 | RESOLVED |
| 21 | W | 放款三处日期无约束 | disbursement_date 单一真相源 | PARTIAL（流水日期未显式声明，见 NW） |
| 22 | W | 角色中间件未排期 | §4 矩阵 + 周独立交付 | RESOLVED |
| 23 | W | Excel 文件名/去向不符 | 按磁盘真实文件重写 | RESOLVED（V5 两份并存小瑕疵 NW13） |
| 24 | W | 历史数据未量化/未排期 | 显式排期 + 附录 C 顺序 | RESOLVED |

**汇总**：RESOLVED 19 / PARTIAL 3（F3、F4、W17）/ OPEN 0。

---

## 第二部分：6 维度复审 v2.0（新引入问题）

### 维度 1 — 完整性：PARTIAL
- NF4：invoices/billings/repayments 无 reversal_of_id，红冲配对无法表内表达。
- NF6：调配归还（已调配→已归还）无事务链路设计（§3.6 未列归还）。
- NW3：计费生成无合同 end_date/状态终止规则。
- NW11：§3.4 "created_by 业务表必填"与 §3.2 字段表不符。

### 维度 2 — 一致性：PARTIAL
- NW6：users.role 含 ADMIN，但 §1.3/§4 无 ADMIN 定义。
- NW8：contracts.monthly_rent 含税，未列入 §1.6 例外与附录 B。
- NW12：§3.2 分域小计错（交付运营"5 张"实 6；资金域重复计 idempotency_keys）。
- NW10：direction 字段长度与枚举字面临界（次要）。

### 维度 3 — 可行性：**FAIL（DDL/SQL 层真错）**
- **NF1**：调配 OUT/IN 两条流水共用 `idempotency_key='allocate:{allocation_id}'`，与 `uq_ct_idem` 唯一索引冲突，第二条 INSERT 必失败，调配跑不通。
- **NF2**：`chk_reversal` CHECK 含 `EXISTS(SELECT ...)` 子查询，PG 禁止，建表报错。
- **NF3**：§5.2 池余额 SQL 引用不存在的 `status_raw` 字段。
- **NF4**：§5.6 对账 SQL 三表 JOIN 未先聚合 → m×n 行乘放大，对账数字失真。
- **NF5**：可调余额 `allocatable = max(0, net_position − frozen_out)` 重复扣减调配额。走查：A 注入 5M、调出 3M → net_position=2M、frozen_out=3M → allocatable=0（应=2M），正常项目被锁死。
- NW1：等额本息 installment 未约定取整/末期尾差。
- NW2：计费示例验算正确（100000×16/30=53333.33，价税分离对）。
- NW4：billings 唯一索引 (contract_id, period_index) 与"每订单计费"冲突。
- NW5：rate 字段无 CHECK [0,1)，附录 B 写了约定但 DB 不兜底（/100 教训）。

### 维度 4 — 风险识别：PARTIAL
- NW7：红冲再红冲、红冲与调配状态联动未定义。
- NW9：超开 tolerance=0 卡正常业务；审批留痕 action 未定义。

### 维度 5 — 优先级：WARNING
- NW14：一期 6-8 周对扩 40% 的范围偏紧，建议 10-12 周或砍二期。
- PASS：RBAC/审计/幂等/测试/历史初始化前移正确；DoD 大多可执行。

### 维度 6 — 可测试性：PARTIAL
- NW10/NW15：DoD 依赖人工对 Excel 难入 CI；audit_logs REVOKE 与 ORM INSERT 关系含糊。
- NW16：调配归还无测试覆盖（与 NF6 呼应）。

---

## 新问题清单（FAIL > WARNING）

### FAIL（6 条）

| 编号 | 章节 | 问题 | 建议 |
|---|---|---|---|
| NF1 | §3.6/§3.3 | 调配两流水共用 idempotency_key 撞唯一索引 | 键加方向后缀 `:OUT`/`:IN`；整笔幂等交通用层 + allocations 约束 |
| NF2 | §3.3 | chk_reversal CHECK 含子查询 PG 拒绝 | 删 CHECK；方向校验移 service 层 + is_reversal 标志 |
| NF3 | §5.2 | 池余额 SQL 引用不存在的 status_raw | 重写：红冲反向记录参与 SUM 自动抵消 |
| NF4 | §5.6 | 对账 SQL 三表 JOIN 行乘放大 | CTE 先聚合再 JOIN |
| NF5 | §5.1/§5.2 | 可调余额公式重复扣减 | `allocatable=max(0,net_position)`，删 frozen_out |
| NF6 | §3.3 | billings 唯一键与"每订单计费"冲突 | 唯一键改 `(order_id, period_index)` |

### WARNING（16 条）

| 编号 | 章节 | 问题 |
|---|---|---|
| NW1 | §5.5 | installment 未约定取整/末期尾差 |
| NW3 | §5.3 | 计费无 end_date/状态终止规则 |
| NW4 | §3.2/§3.7 | invoices/billings/repayments 缺 reversal_of_id |
| NW5 | §3.3 | rate 字段无 CHECK [0,1) |
| NW6 | §1.3/§4 | ADMIN 角色未定义 |
| NW7 | §3.5/§3.7 | 红冲再红冲、红冲与调配联动未定义 |
| NW8 | §1.6/附录B | monthly_rent 含税未入例外清单 |
| NW9 | §5.6/§6.2 | tolerance=0 + 审批 action 未定义 |
| NW10 | §8.5 | Excel 对账难入 CI（CSV fixture） |
| NW11 | §3.4 | created_by 必填口径矛盾 |
| NW12 | §3.2 | 分域小计错 |
| NW13 | §12 | 商机5090 V5 两份并存未确认 |
| NW14 | §10 | 工期 6-8 周偏紧 |
| NW15 | §3.3/§9.4 | audit_logs REVOKE 与 ORM 关系含糊 |
| NW16 | §3.6/§8.3 | 调配归还无事务/无测试 |

---

## 总评

| 维度 | 结论 |
|---|---|
| 1 完整性 | PARTIAL |
| 2 一致性 | PARTIAL |
| 3 可行性 | **FAIL**（NF1–NF5） |
| 4 风险识别 | PARTIAL |
| 5 优先级 | WARNING |
| 6 可测试性 | PARTIAL |

**v2.0 可否进入开发：不可。**

骨架层面把 v1.0 的 6 FAIL + 18 WARNING 大部分接住（四张新表立得对、状态机/单位对照表/Excel 文件名/计费示例都对），实质前进一大步。但"真要落地"暴露 6 个新 FAIL：NF1（调配）+ NF5（可调余额）任一条都让资金池模块上线第一天出可见错误；NF4 直接打"对账"痛点。均为 v2.0 新引入，非 v1.0 遗留。

**仍需补的 TOP 3**：
1. NF1 + NF5（调配去重键 + 可调余额公式）——资金池承重墙，开发前改对并走查数值。
2. NF2 + NF3 + NF4（红冲 CHECK 改应用层 + 池余额 SQL 重写 + 对账 SQL 改聚合）——DDL/SQL 必须能跑且算对。
3. NF6 + NW4（billings 唯一键粒度 + 三表红冲外键）+ NW5（rate CHECK [0,1)）——计费/对账/红冲可对账性 + 堵百分数直填。

修完后建议再跑一轮独立复审确认 DDL 全表 `CREATE TABLE` 在 PG16 一次跑通、§5 全部 SQL/算法用真实数值走查通过，再进入开发。
