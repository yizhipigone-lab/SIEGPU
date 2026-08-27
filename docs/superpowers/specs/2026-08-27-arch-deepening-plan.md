# SIEGPU 架构深化实施计划书（#2 → #1 → #4）

> 日期：2026-08-27 | 状态：待用户确认 | 上游：[架构评审报告](./architecture-review-2026-08-27.html)
> 顺序：#2 matched_amount 单一真源 → #1 工作流事件化 → #4 审计装饰器
> 纪律：每项做完即自检；三项全完后做全面逐行验证审计

---

## 0. 总纪律（贯穿全程）

1. **红绿纪律**：每项先写测试（红）→ 实现（绿）→ 全套件回归。测试先行，不跳步。
2. **逐项自检清单**（每项完成后立即执行，不攒批）：
   - [ ] 删除测试：删掉的代码是否在别处原样复活？（浅模块复活的信号）
   - [ ] 全套件绿：pytest 全量 + 相关 e2e 全绿（0 失败）
   - [ ] 语义零变化：对 API 调用方可见的行为（响应 JSON / 状态码 / 错误码）逐字段比对
   - [ ] 新旧代码共存审查：不允许"旧路径还在但没人调用"的僵尸代码
   - [ ] git diff 逐行读：每行改动都能回答"为什么必须改这一行"
3. **终局审计**（三项全完后）：
   - git diff 全量逐行验证（从 HEAD~N 到 HEAD，每一行归属与理由）
   - 每项的"删除测试"结论复核
   - 全套件（pytest + e2e 全套 + 前端 build）最终跑一遍
   - 架构指标复核：散弹枪调用点数（17→0）、matched_amount 实现数（3→1）、手拼审计 dict 数（46→0）

---

## 1. 项目 #2：Invoice.matched_amount 三份实现 → 单一真源

### 1.1 现状（走查证据）

| # | 位置 | 实现方式 | 口径 |
|---|---|---|---|
| A | `backend/app/models/billing.py:80-99` | ORM column_property：旧链接（`Invoice.capital_transaction_id` 指向的流水）+ 新核销行（`payment_settlements` 两路合计，互斥不双计） | 数据库层单一真源 |
| B | `backend/app/services/payment_service.py:218-226` `_invoice_matched()` | Python 两条查询手加：查旧链接流水 + 查核销行 | 手工复刻 A |
| C | `backend/app/services/reconciliation_service.py:84-90`（dim2 内） | 第三遍：SQL 聚合核销行 + 旧链接 | 手工复刻 A |

漂移风险：三份代码实现同一条不变量，任何一份改口径，另两份不会同步。

### 1.2 目标

- **单一真源**：`Invoice.matched_amount` column_property（A）是唯一实现
- B、C 直接读 `inv.matched_amount`，删掉手加聚合
- **删除测试预期**：删除 B、C 的实现后，复杂度不在调用方复活——调用方代码反而变短

### 1.3 步骤

1. **读透 A**：确认 column_property 的加载策略（懒加载/eager）、在 `db.get(Invoice)` 和 `select(Invoice)` 两种取法下都正确求值
2. **红**：写 pytest（追加到 `test_payment.py`）断言 `_invoice_matched` 与 `inv.matched_amount` 一致——先证明两套口径在测试数据下结果相同（防护网）
3. **改 B**：`payment_service.settle()` 内的 `_invoice_matched(db, inv)` → `inv.matched_amount`；删除 `_invoice_matched` 函数
4. **改 C**：`reconciliation_service.dim2_purchase_chain()` 内的聚合 → 读取 `inv.matched_amount`（注意 dim2 是批量查询——确认 column_property 在列表查询下的 N+1 影响；若有 N+1，用 `selectinload` 或维持 dim2 现状并在注释声明"真源是 column_property，此处聚合为性能豁免"）
5. **绿**：pytest 全量 + e2e（payment-control / reconciliation-center / phase2-chain / w5_6 四个涉款 spec）
6. **自检清单执行**（见 §0.2）

### 1.4 风险与对策

| 风险 | 对策 |
|---|---|
| column_property 在批量场景 N+1 | 实测 dim2 耗时；若劣化 >100ms 则 C 保留聚合 + 注释声明豁免理由（真源仍是 A） |
| 红冲口径：核销后发票红冲，matched 是否随红冲减少 | 现有测试已覆盖（test_payment.py 有核销 golden）；跑绿即证 |
| Decimal vs float 比较精度 | 断言用 `== Decimal(...)` 不用 float |

### 1.5 涉及文件

- `backend/app/services/payment_service.py`（删 ~10 行，改 1 行）
- `backend/app/services/reconciliation_service.py`（改 ~7 行）
- `backend/app/tests/test_payment.py`（+一致性断言）

预估：30 分钟内。

---

## 2. 项目 #1：工作流 after_action 17 散弹枪 → flush 事件

### 2.1 现状（走查证据）

`workflow_service.after_action(db, project_id)` 被手动散布在 9 个 service 文件、17 个函数体里：

- `acceptance_service.py` ×1（approve 内）
- `billing_service.py` ×2（create_billing / device 计费）
- `capital_service.py` ×1（record_transaction 内）
- `contract_service.py` ×1（create/update 内）
- `confirmation_service.py` ×1
- `device_service.py` ×2（stage 推进 / 点亮）
- `invoice_service.py` ×1（create_invoice 内）
- `leasing_service.py` ×3（disburse / add_disbursement / 节点推进）
- `order_service.py` ×4（create / stage / light-on / 批次）
- 其他（profit / sales_order / repayment…）若干

每次新增被追踪实体 = 改新 service + `_TABLE_CLASSES` 白名单 + `_FK_TO_PROJECT` + 模板 + 前端 STEP_HINTS + roleGuide.ts —— 六文件散弹枪。

### 2.2 目标

- **单点事件**：SQLAlchemy `after_flush` 监听器扫描 dirty 实体 → 按 `_TABLE_CLASSES` 判定项目 → 集中调 `_refresh_steps`
- 17 个 service 内的手动调用全部删除——**service 不再知道工作流的存在**
- 对外行为零变化：flush 后步骤刷新的时序与现在一致

### 2.3 步骤

1. **盘点与快照**：grep 全部 `after_action` 调用点建清单（17+ 个）；写一个 pytest 快照测试——对每类实体做一次写操作，断言 workflow steps 的推进结果（防护网，改动前先记录现状）
2. **红**：新测试 `test_workflow_auto_refresh.py`——直接调 service 层写操作（不调 after_action），断言步骤自动推进（当前红：没人刷新）
3. **实现监听器**（`workflow_service.py` 内新增）：
   ```python
   @event.listens_for(Session, "after_flush")
   def _auto_refresh_workflow(session, flush_context):
       # 收集 dirty 实体 → 按 _TABLE_CLASSES 映射 project_id → 去重 → 逐项目 refresh
   ```
   注意：
   - `after_flush` 在 commit 前触发；refresh 本身再写 DB 会在同一事务里（可接受——回滚时步骤也回退，语义自洽）
   - 刷新内部会再 flush → 必须防递归（`_refreshing` thread-local/flag）
   - 性能：只处理 dirty 中真正属于 `_TABLE_CLASSES` 的实体，其余跳过
4. **删除 17 个调用点**：service 内 `from ... import workflow_service as _wf` + `_wf.after_action(...)` 全部删除
5. **绿**：pytest 全量（450+ 用例里大量依赖步骤推进的测试就是天然回归）+ e2e 全套（wizard-workspace / phase2-chain / device-flow-wizard 都验证步骤推进）
6. **自检清单执行**

### 2.4 风险与对策

| 风险 | 对策 |
|---|---|
| 递归 flush（refresh 内再写库再触发事件） | thread-local 递归保护 + 单测覆盖 |
| 端点 commit 前步骤已推进但 commit 失败回滚 | 回滚后步骤一起回退——语义自洽（本来就在同一事务），现有 service-不-commit 铁律保证 |
| dirty 实体的 project_id 解析失败（中间表无 project_id 直挂） | 沿用 `_FK_TO_PROJECT` 现有解析链；解析不出就跳过（与现状一致——现在漏调 after_action 也是静默跳过） |
| 性能：每次 flush 扫 dirty | dirty 集合通常 <20 实体；映射是 dict 查找；实测 pytest 全量耗时对比（当前 ~20s） |
| `test_hard_gates` 等直接断言调用链的测试可能失配 | 跑红后逐个核对——它们断言的是行为（步骤推进）而非调用路径 |

### 2.5 涉及文件

- `backend/app/services/workflow_service.py`（+监听器 ~40 行）
- 9 个 service 文件（各删 1-4 行调用）
- `backend/app/tests/test_workflow_auto_refresh.py`（新增）

预估：2-3 小时（含测试与回归）。

---

## 3. 项目 #4：审计 46 个手拼 dict → @audited 装饰器

### 3.1 现状（走查证据）

- 15 个 service 文件里 46 处 `from app.services import audit_service as _audit` 函数体内局部导入
- 每处手拼 `after_json={...}` dict，键名自由发挥
- 覆盖靠习惯：`contracts.py:129-134` 端点级软删除**不记审计**（遗漏证据）
- `audit_service.log` 每次调用 `db.get(User, ...)` 校验 user 存在 → N+1

### 3.2 目标

- `@audited(action=..., target=...)` 装饰器：自动捕获写操作前/后状态、统一 JSON 格式、自动提取 actor/target
- 46 个函数体手拼 → 46 个函数签名上的声明式装饰
- **不追求**一次替换全部 46 处（P0 只做核心资金域：capital/payment/leasing/contract 4 个 service ~20 处），其余按接触面渐进迁移
- 装饰器统一 flush 时机（解决 audit 不 flush 的时序陷阱）

### 3.3 装饰器设计（先小后大）

```python
def audited(action: str, target: str):
    """装饰 service 写函数。约定被装饰函数签名含 db 且返回 ORM 实体或 None。
    自动记录：action / target_type / target_id / before→after 关键字段 diff。"""
```

- **before 捕获**：仅对已存在于 session 的实体（update 场景）抓关键字段快照
- **after 捕获**：函数返回后从返回值取 id 与字段
- **不做**：字段级 diff 的自动推导（每个 service 的关注字段不同——P0 用声明式 `fields=[...]` 参数，让装饰器知道抓哪些）

### 3.4 步骤

1. **红**：`test_audit_decorator.py`——装饰一个假 service 函数，断言 audit_logs 表出现正确行（当前红：装饰器不存在）
2. **实现装饰器** `audit_service.audited()`（~60 行）
3. **迁移首批 4 个 service**（capital / payment / leasing / contract）约 20 处调用 → 装饰器；每迁移一个函数跑一次该 service 的测试
4. **修复审计 N+1**：`log()` 里的 `db.get(User)` 校验去掉（user_id 由装饰器从参数拿，不需要查库校验——FK 约束兜底）
5. **补漏**：contracts.py 端点软删除遗漏的审计——用装饰器补上（这是走查发现的实际遗漏，顺手修）
6. **绿**：pytest 全量 + e2e（audit-trail spec 专门验证审计留痕）
7. **自检清单执行**

### 3.5 风险与对策

| 风险 | 对策 |
|---|---|
| 装饰器与 service 的 flush 时序冲突（audit 行 vs 业务行同事务） | 装饰器内只 add 不 flush——沿用"endpoint commit"铁律 |
| 被装饰函数签名不统一（有的有 actor_id 有的没有） | 装饰器按参数名探取（actor_id/user_id/created_by 任一）；都没有则记 None |
| 迁移期间新旧两种写法并存 | 每个函数迁移后立即删除旧调用，不保留双轨；未迁移的 26 处保持现状（渐进策略，计划书明示） |
| audit JSON 格式变化影响 e2e 断言 | audit-trail e2e 只断言存在与 action 名——字段级 diff 不会破坏；跑绿验证 |

### 3.6 涉及文件

- `backend/app/services/audit_service.py`（+装饰器 ~60 行）
- `backend/app/services/capital_service.py`（~8 处迁移）
- `backend/app/services/payment_service.py`（~5 处）
- `backend/app/services/leasing_service.py`（~4 处）
- `backend/app/services/contract_service.py`（~3 处）
- `backend/app/api/v1/endpoints/contracts.py`（补软删除审计）
- `backend/app/tests/test_audit_decorator.py`（新增）

预估：2-3 小时。

---

## 4. 终局审计（三项全完后）

### 4.1 逐行验证流程

1. `git log --oneline` 列出本批全部 commit
2. 每个 commit `git show --stat` + `git show` 逐行读：
   - 每行改动归属哪个项目（#2/#1/#4）
   - 每行删掉的代码是否在别处复活（僵尸检查）
   - 每行新代码是否有对应测试
3. 架构指标复核：
   - `grep -c "after_action" backend/app/services/*.py` → 期望 0（监听器内除外）
   - `grep -c "_invoice_matched" backend/app/` → 期望 0
   - `grep -c "import audit_service" backend/app/services/*.py` → 期望降至 ~4（未迁移的 service 保留）
4. 全套件终跑：pytest 全量 + e2e 全套（73 个）+ 前端 type-check + build
5. 产出审计报告（markdown，含逐项结论与证据）

### 4.2 通过标准

- pytest ≥ 455 passed（现有 450+ 新增 ~5-8 个）0 failed
- e2e 全套 ≥ 73 passed 0 failed
- 前端 type-check + build 通过
- 三项架构指标达标（见 4.1.3）
- 逐行验证零"无法解释的改动"

---

## 5. 执行顺序与检查点

```
┌─ #2 matched_amount（30min）─┐
│  红 → 改B → 改C → 绿 → 自检 │
└──────────┬──────────────────┘
           ▼  自检通过才进下一项
┌─ #1 after_action 事件化（2-3h）─┐
│  快照 → 红 → 监听器 → 删17处 → 绿 → 自检 │
└──────────┬──────────────────┘
           ▼  自检通过才进下一项
┌─ #4 审计装饰器（2-3h）─┐
│  红 → 装饰器 → 迁移4service → 补漏 → 绿 → 自检 │
└──────────┬──────────────────┘
           ▼
┌─ 终局审计（1h）─┐
│  逐行验证 + 指标复核 + 全套件终跑 + 审计报告 │
└─────────────────┘
```

任何一项自检不通过：停下修复，修好并复检通过后才进入下一项；不带着已知问题前进。
