# SIEGPU ERP 开发接力（Handoff）

> **最后更新**：2026-08-08
> **最近里程碑**：角色化首页 + 职责引导交付完成（pytest 187 绿 / e2e 44 绿 / 浏览器 4 角色验证）
> **当前分支**：`main`　**工作区状态**：大量未提交改动（设备层升级 + UX 增强），**未 git commit（用户未授权）**
> **给接手者**：先读「§3 当前进度」和「§4 铁律」，再决定从哪接。

---

## 1. 这是什么项目

SIEGPU —— **算力租赁 ERP**（GPU 服务器租给客户、走金租融资、按台计费折旧）。
技术栈：FastAPI + Vue3/naive-ui + PostgreSQL 16 + Docker Compose。
主线工作：把管理粒度从「批次」升级到「单台设备」的一期工程（W1-2 → W7-8 分期推进）。

## 2. 怎么跑起来 / 怎么验证

```bash
# 起全栈（db / backend :8000 / frontend :8080）
docker compose up -d

# 后端测试（基线 187 条，W7-8 后目标 ~220）
docker compose exec backend pytest app/tests/ -q

# 前端类型检查 + 构建（host 上有 node_modules，可直接跑）
cd frontend && npm run build          # = vue-tsc + vite build
# 注意：vue-tsc 查不出 Vue 模板标签错误，靠 vite build 才抓得到（已踩过）

# e2e（Playwright，基线 44 条）
cd e2e && npx playwright test
```

**账号**（密码统一 `sie123`，见 `backend/app/seed.py`）：
| 登录名 | 角色 | 职责 |
|---|---|---|
| admin | ADMIN | 全局 |
| cfo | FINANCE_DIRECTOR | 财务总监，看全部 |
| buyer | PROCUREMENT | 采购（第 1-4 步） |
| delivery | DELIVERY | 交付（第 5-8 步） |
| finance | FINANCE_STAFF | 财务专员（第 9-11 步） |

## 3. 当前进度

### ✅ 已完成并端到端验证

| 模块 | 内容 | 关键文件 |
|---|---|---|
| 设备层 W1-2 | 设备实体、7 节点状态机 | `backend/app/models/device.py`、`services/device_service.py` |
| 设备层 W3-4 | 一机一卡资产、按台计费 | `services/device_service.py`、`utils/depreciation.py` |
| 设备层 W5-6 | 双轨防双计、审计闭环（4 项已修） | `services/device_service.py` |
| 角色化菜单 | 按角色过滤 + 顶栏逃生口 + 路由守卫 | `frontend/src/utils/roleMenu.ts`、`layouts/MainLayout.vue`、`router/index.ts` |
| **角色化首页 + 职责引导**（最新） | 首页按角色变脸：职责横幅 + 待办主角 + 精简 KPI + 11 步流程弹窗高亮 | `frontend/src/utils/roleGuide.ts`、`views/Dashboard.vue` |

**最近一轮验证证据**：vue-tsc 绿 / Docker build 绿 / 浏览器 4 角色（buyer·delivery·finance·cfo）真点全过 / e2e 全量 44 绿（53s）零回归。

### ⏳ 未完成（按建议优先级）

1. **【最大一块】后端一期 W7-8 —— 金租双模式权属分叉 + 售后回租出售 + 放款联动**
   - 详细 5-Phase 计划已就绪：`.claude/plans/cheeky-hopping-shore.md`（4 条用户决策已锁定）
   - 权威规格：`docs/superpowers/specs/2026-08-04-siegpu-upgrade-plan.md` §2.4
   - 要点：① `settle_ownership`（上架时按 leasing_mode 派生权属，仅填 None、显式入参优先）② 售后回租出售全链路（`POST /devices/{id}/leaseback-sale`，折旧截断 + off_balance + 长期应付款 + 出售损益钩子位）③ 放款阈值达成自动建金租 leasing 申请 ④ 新表 `long_term_payables` + orders/devices 加列 + 0008 迁移（schema.sql 双写）
   - 基线门槛：pytest 187 全绿基础上新增 ≥25 条，纯函数 100% 覆盖

2. **UX 候补小项**（用户提过但未排期，等拍板）：
   - 真正按角色拦截 **API 权限**（目前只做了前端菜单/路由过滤，后端 API 未拦）
   - 首次登录强制改密
   - 表单单位强提示
   - 审计查看 UI
   - 角色化首页 3 个可调点：①待办卡太长可加分页/折叠 ②职责横幅关闭后无召回入口 ③flowRange 基于 11 步流程，18 步默认模板项目步号对不上

## 4. 铁律（必读，违反会出事）

- **🚫 不 git commit** —— 用户未授权。改动留在工作区，`git diff --stat` 评估即可。
- **端到端验证铁律** —— 实现只在「浏览器真点能验证」时才算完，「后端跑通」不是终点。
- **分析必须验证不猜测** —— 下结论前实测/读代码/拿原始数据；多假设逐一排除，不堆「可能 A/B」。
- **Docker 镜像无 source mount** —— 每次改代码必须 `docker compose build <svc>` + `up -d <svc>`。
- **每期结束 pytest + e2e 必须全绿**；新增测试 ≥25 条/期；纯函数 100% 覆盖。
- **schema 改动**：alembic 迁移 + `schema.sql` 双写 + parity 测试，**必须可逆**。
- **开发质量三规则**：先问清楚再动手 / 出结果后自检迭代 / 不破坏现有功能（向后兼容）。
- **回答时间戳**：每轮回复开头打印开始时间，末尾附「当前时间 + 本次回答经过」。

## 5. 关键文件地图

**前端**（`frontend/src/`）
- `utils/roleMenu.ts` —— 菜单过滤单一事实源（改菜单只动这里）
- `utils/roleGuide.ts` —— 角色引导单一事实源（改职责文案只动这里）
- `utils/role.ts` —— 角色中文名 `roleName()`
- `views/Dashboard.vue` —— 首页双分支（角色化 / 原财务）
- `layouts/MainLayout.vue` —— 侧栏 + 顶栏「我的角色/全部菜单」逃生口
- `router/index.ts` —— 路由守卫（workspace 对所有角色放行）
- `stores/auth.ts` —— `auth.role`（pinia）+ localStorage `token/role/displayName`
- `views/DevicesView.vue` —— 设备页（W7-8 要在此加「回租出售」按钮 + 抽屉）
- `views/LeasingView.vue` —— 金租页（W7-8 要加 financing_type/leasing_mode/materials 三字段）

**后端**（`backend/app/`）
- `services/workflow_service.py` —— `_device_flow_steps` 11 步权威流程 + `get_my_tasks`（按 doer_role 过滤派活）
- `services/device_service.py` —— 设备状态机 + 资产/off_balance 同步（W7-8 改 `_sync_device_asset` 上架分支）
- `services/leasing_service.py` —— 金租 9 节点 `create_process`（W7-8 零改复用）
- `utils/depreciation.py` —— 折旧（W7-8 加 `truncated_schedule` 截断）
- `db/schema.sql` + `alembic/versions/` —— schema 双写（W7-8 加 `0008_leaseback_and_disbursement.py`）

**规格 / 计划**
- `docs/superpowers/specs/2026-08-04-siegpu-upgrade-plan.md` —— 升级总规划（权威）
- `.claude/plans/cheeky-hopping-shore.md` —— W7-8 详细实施计划

## 6. 已知坑（踩过，别再踩）

| 坑 | 说明 / 规避 |
|---|---|
| **Dashboard 待办卡 title 必须保「待处理」** | e2e 用 `.n-card hasText:'待处理'` 定位；角色化首页横幅文本必须**避开**「待处理」三字，否则 strict locator 撞多卡 |
| **cfo 菜单别收紧** | e2e 全程用 cfo 登录，收紧 cfo 菜单会大面积回归 |
| **vue-tsc 查不出模板标签错误** | `<n-statistic .../>` 自闭合后多余 `</n-statistic>` vue-tsc 绿但 vite build 报 Invalid end tag；改完前端务必跑 `npm run build` |
| **e2e 写共享 dev DB，无隔离** | buyer 账号已积 43 条待办（E2E-商机xxx 等脏数据），首页偏长；生产环境若真多待办同理，属可调点 |
| **naive-ui NSelect Playwright 三坑** | placeholder 不在 input / 残留隐藏 option / 过渡动画时序；见 memory `naive-ui-select-playwright` |
| **wizard-workspace e2e 用 18 步默认流程** | 首页待办必须按 myTasks 泛渲染，不能假设 11 步 |

## 7. 给下一步的建议

**接手者第一件事**：跟用户确认方向——是推进 W7-8 后端（计划已就绪，可直接进 Phase 1），还是挑一条 UX 小项。**不要未经确认就开新实现**（规则1：先问清楚）。

W7-8 若启动，按计划文件顺序执行：Phase 1 数据模型 + 0008 迁移（最高风险，动 schema 最先做、最小集）→ Phase 2 settle_ownership + 纯函数 → Phase 3 回租出售全链路 → Phase 4 放款联动 → Phase 5 schema/向导/前端/e2e。每期结束 pytest + e2e 全绿才收。

## 8. 跨会话 memory（`~/.claude/projects/e--1target-SIEGPU/memory/`）

- `project-siegpu-erp.md` —— 项目设计 v2.0 + 代码骨架 + 运行方式
- `siegpu-upgrade-device-layer.md` —— 设备层升级进度（W1-6 完成，W7-8 待做）
- `role-based-menu.md` —— 角色化菜单
- `role-dashboard-guide.md` —— 角色化首页 + 职责引导（最新）
- `end-to-end-verification-iron-law.md` —— 端到端验证铁律
- `naive-ui-select-playwright.md` —— naive-ui 下拉 e2e 封装
