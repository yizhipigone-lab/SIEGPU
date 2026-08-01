# 项目成果审计报告 — SIEGPU 代码骨架

> 审计对象：backend/ + frontend/ + docker-compose.yml（已 docker compose up 端到端跑通）
> 审计日期：2026-07-31
> 审计方式：独立 `code-reviewer` agent，三角色（架构/功能/测试）最高标准代码审计
> 审计结论：**FAIL 0 / WARNING 12 / PASS 8 — 地基稳，可在此基础上继续实现业务模块，但资金池开工前需修 TOP 7**

---

## 审计对象与范围

| 维度 | 内容 |
|---|---|
| 后端 | schema.sql（19 表）、app/{models,core,utils,api,tests}、seed.py、alembic/env.py、Dockerfile、requirements.txt |
| 前端 | src/{main,App,router,api/client,stores/auth,views/Login,views/Dashboard}、nginx.conf、Dockerfile、package.json |
| 编排 | docker-compose.yml |
| 方法 | 全部结论 Read/Grep 实读，引用 file:line |

## 结论汇总

一句话总评：骨架质量明显高于一般 AI 生成代码——19 表 DDL 与 ORM 列级对齐几乎零错、算法纯函数有 17 条精准单测覆盖、端到端确实跑通。但存在两处会在下一步业务模块立刻咬人的结构性缺陷：(1) DDL 真相源分裂（schema.sql 部分唯一索引 vs ORM 非 UniqueConstraint，alembic 无法直接生成迁移）；(2) 软删除无模型级默认过滤，资金池聚合一旦漏带 `deleted_at IS NULL` 会直接算错余额。

**可否继续实现业务模块：可以**，但"资金池"开工前必须先修 TOP 7。

## 逐项发现（FAIL > WARNING > PASS）

### WARNING-1 | DDL 真相源分裂：ORM 唯一约束与 schema.sql 部分索引不一致
- 文件：models/capital.py:14-16、models/billing.py:14-18 vs schema.sql:202,320,321
- 问题：`capital_transactions.idempotency_key` 在 DB 是部分唯一索引 `WHERE idempotency_key IS NOT NULL`，模型写成普通 `UniqueConstraint`，约束名也不同。billings 同样两条部分索引被写成普通 UniqueConstraint。
- 影响：运行期无碍，但 `alembic revision --autogenerate` 会生成破坏性 diff；billings 的 `(order_id, period_index) WHERE deleted_at IS NULL` 是语义承载的（软删后允许重开）。
- 建议：模型改 `Index(..., unique=True, postgresql_where=text(...))`，名字与 DB 对齐。

### WARNING-2 | alembic 无法生成迁移（缺模板 + 无基线 + drift）
- 文件：alembic/（缺 `script.py.mako`）、env.py:25
- 问题：缺 script.py.mako；无基线迁移无 stamp 流程；env.py 未设 compare_type/compare_server_default；CHECK/触发器/部分索引模型未表达。
- 建议：定 DDL 单一真相源（schema.sql 或 alembic），补 script.py.mako + compare_type。

### WARNING-3 | 软删除无模型级默认过滤——资金池聚合隐患
- 文件：19 模型无 `__mapper_args__`/`with_loader_criteria`；仅 auth.py:17 一处手写过过滤
- 问题：16 张表有 deleted_at 但无默认查询过滤，全靠人记。
- 影响：资金池 `net_position/pool_balance` 纯函数对脏数据零防御，漏过滤会双向算错。
- 建议：with_loader_criteria 默认带 `deleted_at IS NULL`，显式 include_deleted 才绕过。

### WARNING-4 | JWT_SECRET 默认值无启动校验
- 文件：config.py:8、docker-compose.yml:22
- 问题：默认 "change-me-in-prod"，不设环境变量则静默用已知常量，可伪造任意 role token。
- 建议：生产环境启动期校验，默认/弱值拒绝启动。

### WARNING-5 | CORS allow_origins=["*"] + allow_credentials=True
- 文件：main.py:8-14
- 判断：用 Bearer 不用 cookie，实际可利用性有限，内网短期可接受；但 allow_credentials=True 多余。
- 建议：allow_credentials=False，origins 收敛白名单。

### WARNING-6 | backend 无 .dockerignore，COPY . . 全量进镜像
- 文件：backend/Dockerfile:6
- 问题：会把 __pycache__/.venv/.env/uploads/.git 打进镜像，.env 含密钥则永久烘焙进层。
- 建议：新增 backend/.dockerignore 排除密钥与缓存。

### WARNING-7 | healthz 降级仍 200 + 泄漏 DB 错误；backend 无 healthcheck
- 文件：endpoints/health.py:15-16、docker-compose.yml（backend 无 healthcheck）
- 建议：DB 失败返 503 且不回 str(e)；backend 加 healthcheck。

### WARNING-8 | 前端响应拦截器返回 r.data 造成 axios 类型"说谎"
- 文件：api/client.ts:12-21、stores/auth.ts:11、Dashboard.vue:16-19
- 建议：用 module augmentation 声明返回类型，建 TS 类型。

### WARNING-9 | 登录页种子账号硬编码进前端 bundle
- 文件：views/Login.vue:10-11
- 建议：生产构建清空默认值（ref('')）或仅 dev 预填。

### WARNING-10 | 前端无 lockfile + Dockerfile 用 npm install
- 文件：frontend/Dockerfile:3-4
- 建议：提交 package-lock.json，改 npm ci。

### WARNING-11 | 无 IntegrityError → 业务异常映射
- 文件：core/exceptions.py
- 问题：模型未在 Python 侧重复 CHECK，写入非法值 PG 抛 CheckViolation 无 handler，500 泄漏 SQL。
- 建议：加 IntegrityError handler → 409/422 + 稳定 code；Pydantic Literal 拦枚举。

### WARNING-12 | idempotency_keys.response_status 类型与 schema 不符
- 文件：models/user.py:46 vs schema.sql:392（SMALLINT vs 推断 Integer）
- 建议：显式 SmallInteger。

### PASS（确认正确）
- **PASS-A**：19 表列级对齐几乎零错（billings.reversal_of_id 自引用、invoices.capital_transaction_id、互引用 ALTER FK、contracts.party_id 多态无 FK 处理得当；models/__init__ 19 表全导出）。
- **PASS-B**：还款末期尾差精确闭合（Σprincipal == principal，q2 恒等映射不被二次取整破坏）。
- **PASS-C**：add_months 月末夹紧无链式退化（从放款日独立推算）。
- **PASS-D**：计费边界（点亮日=月末计 1 天、价税分离闭合与 schema CHECK 一致）。
- **PASS-E**：bcrypt 72 字节截断，verify 异常吞没合理，无 passlib 残留。
- **PASS-F**：RBAC 取角色自 DB 真值而非 JWT claim，对 sub=None/停用/软删均收敛 401。
- **PASS-G**：前端登录 content-type 匹配 OAuth2PasswordRequestForm；App 包了 NMessageProvider；Pinia 先于 router install。
- **PASS-H**：seed 幂等；compose db healthcheck + backend depends_on condition 正确。

## 资金池开工前必须先修的 TOP 7
1. **[W3] 软删除默认过滤**（with_loader_criteria）——资金池余额计算生命线。
2. **[W1] 对齐 idempotency_key 部分唯一索引**（模型 vs DB 名字/谓词一致）。
3. **[W4] 启动期强制校验 JWT_SECRET**。
4. **[W2] 定 DDL 真相源 + 补 alembic 可用性**（script.py.mako、compare_type、受控迁移）。
5. **[新增] 建立写事务范式**：service 层 `with db.begin()` 或显式 commit/rollback，调配=OUT+IN+allocation 原子提交。
6. **[W11] IntegrityError 全局 handler + Pydantic 枚举校验**。
7. **[W7] backend 加 healthcheck + healthz 不永远 200**。
