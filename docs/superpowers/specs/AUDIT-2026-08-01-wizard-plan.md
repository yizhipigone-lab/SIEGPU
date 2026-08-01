# SIEGPU 向导式工作台 — 设计计划书质量审计

> 审计日期：2026-08-01 | 审计对象：`2026-08-01-siegpu-wizard-workflow-design.md`（DRAFT v1.0）
> 审计方法：逐条对照现有代码（backend/app/services/ 等 21 个 service、db/schema.sql 24 表、72 测试、frontend/src/router、e2e/）+ 依赖文档 [v3.1](./2026-08-01-siegpu-erp-design-v3.md) §2.1 17 步全链路。所有结论均引用实际代码/章节，不靠推断。

---

## 总览

| 维度 | 判定 | 一句话结论 |
|---|---|---|
| 1. 完整性 | **WARNING** | R1-R7 全部有对应设计，但 R2 模板步骤定义、R5 跨步骤数据传递只有骨架 |
| 2. 一致性 | **FAIL** | 4 处以上章节间直接矛盾：after_action 同步 vs 异步、模板步数、seq 编号、角色模型 |
| 3. 可行性 | **WARNING** | 引擎/抽屉方案整体可行；after_action 异步缓解无基础设施支撑是最大硬伤 |
| 4. 风险识别 | **FAIL** | 第10章仅 4 条，漏掉旧项目进度推断、静默失败、并发竞态、completion_check 越权 4 类关键风险 |
| 5. 优先级 | **WARNING** | Phase 2 把"低风险新代码 + 最高风险 8 处埋点"塞一起，应拆分 |
| 6. 可测试性 | **WARNING** | "8+ 用例 / 1 全流程 / 3 E2E"不可量化，缺关键路径用例清单 |

**Verdict: WARNING — 2 项 FAIL 维度（一致性、风险识别）需修订后才能批准进入实现。**

---

## 1. 完整性 — WARNING

### R1-R7 覆盖核对

| # | 需求 | 对应设计 | 判定 |
|---|---|---|---|
| R1 | 首页待办 + 项目工作台 | 6.1 Dashboard 待办卡片 + 6.2 ProjectWorkspace.vue | 完整 |
| R2 | 流程完全可配置 | 3.1 模板 + 4.1 update_step_config + 第5章 模板 CRUD API | 有机制无定义：3 个模板的 17 步具体步骤定义、每步 drawer/prefill/completion_check 全集从未枚举；v3.1 2.1 只有 17 步业务动作，不含 wizard 需要的 schema 元数据 |
| R3 | 关键步骤抽屉 | 6.3 StepDrawer + 6 个 drawer_schema | 6 个抽屉未映射到具体是哪几步，"其他"到简单步骤跳转含糊 |
| R4 | 角色归属 + 按角色过滤待办 | 3.4 steps.role + 4.1 get_pending_tasks(user_role) | 依赖角色系统，但 v3.1 审计 C3 已确认 require_role（core/deps.py:28）定义后从未被任何端点调用，所有端点只要登录 |
| R5 | 步骤间数据自动传递 | 3.4 prefill | 只演示了 {{project_id}}，而"上一步产出到下一步预填"真正需要的 order_id / sales_order_id / contract_id / acceptance_id 等跨步骤 ID 无任何传递机制 |
| R6 | 步骤完成自动检测 | 3.4 completion_check + 4.2 after_action + 4.3 轮询 | 覆盖有洞，见一致性问题4与风险3 |
| R7 | 不破坏现有功能 | 第8章 向后兼容 | 24 表 + 72 测试基线已核实（schema.sql 24 个 CREATE TABLE、tests/ 72 个 def test_） |

### 关键缺失（非对照代码不可见）

- **Step 1 项目建立永远无法被标记完成**：Phase 2 只写了"POST /api/projects 扩展：创建项目时自动关联 workflow"，但没有任何机制标记 Step 1 done 并推进到 Step 2（after_action 的 8 个调用点里没有 project 创建）。若不加，current_step 永远停在 1，向导不启动。4.1 需补 create_workflow 内同步标记 Step 1。
- **向导步骤集与 17 步无映射表**：v3.1 2.1 的 17 步（Step 5 银行流贷、Step 8 金租申请、Step 10 采购验收等）和 wizard 的 steps JSONB 之间没有一份"每步到 module/action/drawer/prefill/completion_check"的逐条映射，实现期必然靠人脑补。

---

## 2. 一致性 — FAIL

> 4 处以上章节间直接矛盾或数据契约不吻合。

1. **[HIGH] after_action 同步 vs 异步自相矛盾（4.2 与第10章）**
   4.2 伪代码 after_action(db, project_id) 是同步嵌入 db.flush() 之后（同一事务内）；第10章缓解写"异步执行（db.flush() 后，不阻塞主流程返回）"。两者冲突：同步则每笔业务操作多一次 completion_check 查询、且 step 状态变更与业务同事务（业务回滚则推进回滚，正确但慢）；异步则脱离事务，须自建会话，且崩溃即丢推进。项目 requirements.txt 无任何异步任务/消息队列（无 celery/arq/rq，main.py 无 BackgroundTask），"异步执行"当前无基础设施可落地。必须二选一并写明：推荐同步事务内推进（原子、免排队基础设施），用 SELECT FOR UPDATE 防并发，牺牲一点写延迟。

2. **[HIGH] 模板步数对不上：自有资金全款"约 10 步" vs 17-3=14（3.1）**
   模板 3 写"跳过 Step 5 银行流贷、Step 8-9 金租，约 10 步"。17 步去掉 3 步应为 14 步（Step 6 自有资金入金、Step 7 预付采购款、Step 16 开票回款核销仍在）。"约 10"无出处。且模板 1"金租直融"与模板 2"流贷+金租"写成"17 步相同，仅步骤参数不同"——两者名称暗示融资路径不同，为何 17 步完全一致？参数差在哪？未定义。模板是 R2 的承重，必须给出每模板的步骤清单 + 差异参数。

3. **[MEDIUM] 步骤编号错位：3.4 示例 seq:1=银行流贷入金 与 v3.1 Step5 / 6.1 "Step 5/17"**
   3.4 的 steps 示例把"银行流贷入金"编为 seq 1；而 v3.1 2.1 中银行流贷是 Step 5，6.1 待办卡片自己也写"商机5090 · Step 5/17"。示例若只是示意应标注"非真实序号"，否则模板 seq 与 v3.1 17 步序号对不上，audit log 的 step_seq 与前端进度条全部错位。

4. **[MEDIUM] 角色模型与 v3.1 权限矩阵冲突（3.4 role 与 v3.1 第6章）**
   steps 只有单个 role 字段，表达不了 v3.1 第6章的"执行人 vs 审批人"分离：采购验收=PROCUREMENT 创建，验收通过/驳回却要 ADMIN/FINANCE_DIRECTOR 审批。待办该推给谁？抽屉操作（approve）需要谁的角色？单 role 字段无法覆盖，需在 steps 里补 approval_role 或按 v3.1 第6章把操作拆成 doer/approver 两步。

---

## 3. 可行性 — WARNING

### 已验证可行（对照代码）

- **8 个 after_action 目标函数全部存在**：capital_service.record_transaction(:112)、leasing_service.disburse(:91)、acceptance_service.approve_acceptance(:49)、billing_service.generate_billing(:22)、confirmation_service.confirm(:49)、invoice_service.reconcile_invoice(:131)、order_service.light_on(:75)、contract_service.create_contract(:11)。均含 db.flush()，机制上可嵌入。
- **StepDrawer 可复用现成 NDrawer 模式**：naive-ui Drawer 已用于 GenericCrud.vue、LeasingView.vue，1 个通用壳 + 6 个表单组件方案成立（实质是 name 到组件注册表，非真"schema 驱动"，措辞过誉但可实现）。
- **双 DDL 源教训已吸收**：Phase 1 同时改 schema.sql + alembic 0003，符合 tests/conftest.py:25 走 schema.sql 的铁律；alembic 现有 0001/0002，0003 接续正确。
- **E2E 落点正确**：e2e/（Playwright）在仓库根，与 v3.1 审计一致。

### 不可行 / 有硬伤

1. **[HIGH] "嵌入 8 个 service 的 db.flush() 之后"表述与代码不符**
   多个目标 service 有多处 db.flush()（capital_service 7 处、order_service 4 处、invoice_service 4 处）。"之后"指哪一处？且低层函数会被复合操作复用——record_transaction 也被金租放款/置换内部调用，嵌入后每次资金写入都触发一次 completion_check 查询（性能噪音）+ 可能在"非目标步骤"上误判。应改为：在 8 个具体业务函数末尾、由 endpoint commit 前统一调用一个 workflow_service.after_action(db, project_id)，并给 8 个函数各自确认 project_id 来源（disburse 只有 process_id，需反查）。

2. **[HIGH] 8 个埋点覆盖不了 17 步 — 约 6 步静默依赖轮询**
   对照 v3.1 2.1：Step 1 项目建立、Step 3 销售订单、Step 4 采购订单创建、Step 8 金租申请、Step 11 交付6阶段、Step 17 盈利测算都不在 8 个调用点内（order_service 埋的是 Step 13 点亮而非 Step 4 采购创建；交付6阶段走 order_service.advance_stage，未埋）。这 6 步只能靠"前端打开工作台轮询"（4.3）补。方案可行，但文档从未声明这个分工——应显式列出"8 步走埋点 / 6 步走轮询 / Step 1 由 create 内联"，否则实现期会以为全自动。

3. **[HIGH] completion_check 动态表名/条件 + PATCH 无角色校验 = 越权推进**
   check_step_completion 用 table(table_name) + 从 JSONB 读列名拼条件；而 PATCH /api/workflows/{project_id}/steps/{seq} 允许任何登录用户改步骤配置。鉴于 v3.1 C3（后端无任何 require_role），任意登录用户可把某步 completion_check.table 指到 users、min_count=1，瞬间"完成"当前步骤、推进向导（伪造进度）。SQLAlchemy 引号会挡注入，但逻辑越权挡不住。PATCH 必须：校验 table 名白名单（限定业务表集合）+ 启用 require_role。

4. **[MEDIUM] R5 跨步骤数据传递没有机制**
   前端待办到抽屉到提交已有 API，但"Step 4 采购订单 id 到 Step 7 预付采购款 / Step 10 采购验收预填"这类上一步产出的 id，{{project_id}} 模板变量覆盖不了。需定义 {{prev_order_id}} 类占位符或 per-step context JSON，或干脆在前端 workspace 里维护"已产出 id 表"。这是 R5 的核心，文档只有 project_id 一个例子。

5. **[MEDIUM] 抽屉是"单个表单"，但验收/确认是多 API 编排**
   采购验收 = create_acceptance + 上传文件 + approve 三个动作；一个 acceptance 抽屉要串 3 个 API。6.3 未定义抽屉"提交动作链"，实现时容易做成一次提交半途而废。

---

## 4. 风险识别 — FAIL

第10章只有 4 条，且其中 1 条缓解方案自相矛盾（见一致性问题1）。至少还缺 6 类风险：

| # | 缺失风险 | 级别 | 建议缓解 |
|---|---|---|---|
| 1 | 旧项目兼容/进度推断（第8章一句"从当前数据状态推断进度"带过，实际是重活）：存量项目没有 workflow 实例，要从 24 张业务表反推当前走到第几步，边界（半路数据、异常状态）极易判错 | HIGH | 单独一节：定义逐步骤推断规则 + 人工确认兜底（推断为"未知"时置 current_step=1 并提示人工校准） |
| 2 | after_action 静默失败导致进度停滞：第8章说 try/except 只记日志，但业务成功、推进失败会让进度条永远卡住，用户无感知、无手动补偿 | HIGH | 前端打开工作台强制 refresh + 待办页显示"进度可能滞后"提示 + 提供手动"标记完成"API 兜底 |
| 3 | 并发竞态/双重推进：两个用户同时操作触发 after_action，无锁地读 current_step 改 current_step 会重复推进或覆盖；refresh_all_steps 与 advance_step 并发同样竞态 | HIGH | advance_step 用 SELECT FOR UPDATE（项目已有先例：leasing_service 放款三重防护），并给 project_workflows.current_step 加乐观锁 |
| 4 | 红冲/撤销与向导状态不同步：v3.1 财务核心是红冲（reverse_transaction / reverse_invoice），一笔满足 Step 7 的付款被红冲后，completion_check 计数归零但 current_step 已推进、步骤仍标 done——向导状态与真实数据脱节 | MEDIUM | 红冲点也挂 after_action（检测当前步数据被撤销则回退状态），或明确"完成状态不可回退、仅靠人工调整"并给 API |
| 5 | 模板 x 17 步映射工作量被低估：3 个模板 x 每步的 drawer/prefill/completion_check 全要手写，completion_check 条件（如 Step 7 预付采购款是金额足额，非 count>=1）各有定制 | MEDIUM | 计划书里单列"17 步 schema 清单"交付物，别当边角料 |
| 6 | 权限矩阵缺口（继承 v3.1 C3）：向导 8 个新端点 + PATCH 改步骤配置，全部只有登录校验，无角色校验 | MEDIUM | 明确向导端点挂 require_role，PATCH 限 ADMIN |

> 第8章提到的"旧项目兼容"只在向后兼容章出现，未进风险矩阵——这恰是最易翻车的存量数据迁移。

---

## 5. 优先级 — WARNING

- **Phase 2 过胖（应拆为 3 段）**：现在一个 Phase 塞了 workflow_service（新代码）+ template_service（新代码）+ POST /api/projects 扩展 + 8 个 API + 在 8 个现有 service 埋 after_action（最高回归风险的改动）。埋点一旦出错会污染现有 72 测试的稳定路径，与大量新代码混在一个 Phase 里，出错难定位。建议：
  - Phase 2a：workflow_service + template_service + 3 表读写（纯新增，低风险）+ 配套单测
  - Phase 2b：8 个 API 端点（薄，读模板/查询）
  - Phase 2c：after_action 埋点（独立提交 + 独立集成测试，只动 8 个函数各加 1 行调用）
- **Phase 4 测试后置**：TDD 角度所有测试堆到最后一个 Phase，违背"改完立刻验证"。至少埋点 Phase（2c）必须同 Phase 出集成测试。

---

## 6. 可测试性 — WARNING

第9章的"8+ 用例 / 1 全流程 / 3 E2E"不可量化、覆盖不全：

1. **"8+ 用例"远不够且无断言清单**：workflow_service 有 9 个公开函数，8+ 约等于每个函数 1 条，edge case 全缺。必须枚举至少以下断言：
   - create_workflow：从模板深拷贝 steps（改项目 steps 不污染模板）
   - advance_step：跳过 required=false 后推进到下一个 required 步；末尾无 next_required 时的终态
   - skip_step 后再 refresh 不复活
   - 乱序完成（用户先做 Step 14 再做 Step 5）到轮询能否正确识别已完成步
   - get_pending_tasks 按角色过滤正确/空角色边界
   - 红冲一笔满足条件的流水到完成状态应如何（与风险4对应）
   - advance_step 并发调用只推进一次
   - 8 个 after_action 埋点各自的集成断言（这 8 处是回归高危区，现有单测完全没提它们）
2. **"1 全流程"应改为至少 3 条**：R2 的核心卖点是"不同项目不同流程"，只跑 1 条 17 步验证不了。至少：金租直融 17 步 / 自有全款（14 步含跳过）/ 1 条自定义改步骤流程，且至少 1 条走 skip 路径。
3. **E2E "3 spec" 建议具名**：工作台进度条推进、抽屉预填+提交、首页待办按角色过滤显示。可量化。
4. **72 测试全绿可量化**（这是唯一数字明确的验收线）。

---

## 优先级排序的问题清单

| 级别 | # | 问题 | 章节 |
|---|---|---|---|
| HIGH | 1 | after_action 同步 vs 异步矛盾 + 无异步基础设施 | 4.2 与第10章 / requirements.txt |
| HIGH | 2 | Step 1 项目建立永远无法标记完成，向导不启动 | 4.1 / 第7章 Phase2 |
| HIGH | 3 | 8 埋点覆盖仅约 11/17 步，6 步静默依赖轮询，未声明分工 | 4.2 与 v3.1 2.1 |
| HIGH | 4 | completion_check 动态表名 + PATCH 无角色校验，越权伪造进度 | 4.3 / 第5章 PATCH |
| HIGH | 5 | 并发双推进无锁 | 4.2 |
| HIGH | 6 | 旧项目进度推断无方案（只 1 句带过） | 第8章 / 第10章 |
| MEDIUM | 7 | 模板步数"约 10"对不上 17-3=14；模板1/2 差异未定义 | 3.1 |
| MEDIUM | 8 | 单 role 字段 vs doer/approver 分离 | 3.4 与 v3.1 第6章 |
| MEDIUM | 9 | 红冲与向导状态脱节 | 第10章 |
| MEDIUM | 10 | R5 跨步骤 id 传递无机制 | 3.4 |
| MEDIUM | 11 | 抽屉多 API 编排未定义 | 6.3 |
| LOW | 12 | seq 编号错位（示例 seq:1 vs v3.1 Step5） | 3.4 |
| LOW | 13 | "schema 驱动"措辞过誉（实为 name 到组件注册） | 6.3 |
| LOW | 14 | 测试全堆 Phase 4，违背改完即验 | 第7章 |

---

## 结论

**Verdict: WARNING — 不建议在一致性（FAIL）与风险识别（FAIL）修订前进入实现。** 优先修 6 条 HIGH：先定 after_action 同步/异步，补 Step 1 完成机制，列明"埋点 vs 轮询"分工表，PATCH 加表名白名单 + require_role，advance_step 加锁，旧项目进度推断单独成节。
