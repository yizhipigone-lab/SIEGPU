# SIEGPU 智能助手 P0 实施计划书

> 日期：2026-08-27 | 状态：P0 已完成（2026-08-27，评审意见已消化） | 上游文档：[设计方案 v1.0](./2026-08-27-siegpu-ai-assistant-design.md)
> 用户拍板：DeepSeek API（非私有化）· 写操作不做 · 增加新手流程指引知识库问答 · 不做晨报

---

## 1. P0 范围（做什么 / 不做什么）

**做：**
1. 右侧侧边栏对话窗口（SSE 流式回答，Ctrl+J 唤起，页面上下文感知）
2. 只读问答：10 个只读工具（看板/资金池/项目/流程/还款/发票/预警/对账/指引检索）
3. 高频意图快路径 fastpath（资金头寸/逾期还款/预警/指引 四类，秒回）
4. **新手流程指引知识库问答**（22 条策展条目：11 步流程 + 术语 + 操作指引 + 角色权限）
5. 反幻觉：金额溯源校验（回答数字必须能对上工具返回，否则标 ⚠️低置信）
6. 成本闸门（单轮 8 次工具调用上限 + 单用户日 20 万 token 配额）+ 失败不炸主系统
7. 会话持久化（assistant_sessions / assistant_messages 两表）
8. 金标集评测（14 题）+ pytest 单元测试

**不做（用户拍板）：** 写操作/确认令牌（L2）、晨报定时推送（L3）、私有化模型、长期认知沉淀

## 2. 文件清单与状态

| # | 文件 | 说明 | 状态 |
|---|---|---|---|
| 1 | `backend/app/core/config.py` | +DeepSeek/闸门配置 | ✅ 已完成 |
| 2 | `backend/app/models/assistant.py` | 会话/消息两表模型 | ✅ 已完成 |
| 3 | `backend/app/models/__init__.py` | 注册模型 | ✅ 已完成 |
| 4 | `backend/alembic/versions/0024_assistant.py` | 建表迁移（纯加表无损可逆） | ✅ 已完成 |
| 5 | `backend/db/schema.sql` | 同步 DDL（双写纪律） | ✅ 已完成 |
| 6 | `backend/app/services/assistant/engine.py` | DeepSeek HTTP：超时/瞬断一次重试/429 不重试/失败返回结构化错误 | ✅ 已完成 |
| 7 | `backend/app/services/assistant/tools.py` | 10 个只读工具 + OpenAI 格式注册表 | ✅ 已完成 |
| 8 | `backend/app/services/assistant/fastpath.py` | 4 类意图快路径（保守识别，漏判回落 agent loop） | ✅ 已完成 |
| 9 | `backend/app/services/assistant/kb.py` | 指引知识库 + bigram 轻量检索 | ✅ 已完成 |
| 10 | `backend/app/services/assistant/prompts.py` | system prompt（金额铁律/数据非指令/只读声明） | ✅ 已完成 |
| 11 | `backend/app/services/assistant/guardrails.py` | 金额溯源校验 + 低置信标记 | ✅ 已完成 |
| 12 | `backend/app/services/assistant/memory.py` | 会话管理 + 日配额统计 | ✅ 已完成 |
| 13 | `backend/app/api/v1/endpoints/assistant.py` | POST /chat（SSE）+ GET /history + POST /reset | ✅ 已完成 |
| 14 | `backend/app/main.py` | 注册路由 | ✅ 已完成 |
| 15 | `docker-compose.yml` | DEEPSEEK_API_KEY 环境变量透传 | ✅ 已完成 |
| 16 | `backend/app/services/assistant/golden_set.json` | 14 题金标集 | ✅ 已完成 |
| 17 | `backend/app/services/assistant/eval.py` | 评测器（无 key 如实报不可评估，不造假） | ✅ 已完成 |
| 18 | `backend/app/tests/test_assistant.py` | 纯单元测试（不依赖 DB/网络） | ✅ 已完成 |
| 19 | `backend/app/tests/test_migration_parity.py` | +0024 双写守护断言 | ✅ 已完成 |
| 20 | `frontend/src/components/AssistantDrawer.vue` | 侧边栏组件（对话流/SSE/快捷问题/上下文芯片） | ✅ 已完成 |
| 21 | `frontend/src/layouts/MainLayout.vue` | 顶栏按钮 + Ctrl+J + 挂载抽屉 | ✅ 已完成 |
| 22 | 联调验证 | pytest + 前端 build + 容器重建 | ✅ 已完成 |

## 3. 执行步骤（剩余）

1. **后端补齐**（#12-13, #16-19）：memory / endpoint / golden_set / eval / 单测 / parity 断言：parity 测试加 0024 段（schema.sql 与 alembic 双写断言）
2. **后端验证**：容器内跑 `pytest app/tests/test_assistant.py test_migration_parity.py`；`alembic upgrade head` 建表
3. **前端组件**（#20-21）：AssistantDrawer.vue（NDrawer 420px 不遮罩、fetch SSE 流式渲染、空会话 4 个快捷问题、上下文芯片显示当前页面、低置信标记高亮）；MainLayout 顶栏加机器人按钮 + Ctrl+J
4. **前端验证**：`pnpm build`（或 npm run build）无 TS 错误；浏览器手测打开/提问/流式渲染
5. **联调**：项目根 `.env` 写入 `DEEPSEEK_API_KEY=sk-...`（你提供）→ `docker compose up -d --build backend frontend` → 实测三类问题（资金头寸/逾期还款/「点亮是什么」）

## 4. 验收标准

| 标准 | 度量 |
|---|---|
| 单元测试全绿 | test_assistant.py + parity 全过 |
| 高频问题秒回 | 资金/还款/预警/指引走 fastpath，单次 LLM 成文 |
| 金额可溯源 | 回答数字对不上工具返回时自动标 ⚠️低置信 |
| 失败不炸主系统 | 无 API key / 网络断开时返回友好降级文案，ERP 其他功能不受影响 |
| 成本有闸 | 超日配额返回配额提示；agent loop 不超 8 轮 |
| 权限天然生效 | 助手沿用当前用户 JWT，接口走 get_current_user |
| 金标集可跑 | 配好 key 后 `python -m app.services.assistant.eval` 出真实通过率 |

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| LLM 幻觉金额 | guardrails 溯源校验（已实现）；fastpath 数字原样引用 |
| Prompt 注入（OCR/备注文本夹带指令） | prompt 数据非指令铁律 + 工具返回包 `<data>` 标记（已实现） |
| DeepSeek 服务抖动 | 瞬断一次重试；失败结构化降级（已实现） |
| 容器内无法出网调 API | 联调时验证；若内网限制需配代理（开放问题） |
| schema.sql / alembic 漂移 | parity 测试守护（#19 待补） |

## 6. 联调记录与后续

- 后端 480 pytest 全绿（含新增 test_assistant.py 纯逻辑+集成两层、parity 0024 断言）
- 容器重建健康，alembic 0024 已应用，assistant_sessions/messages 两表就位
- 未配置 key 时 SSE 返回友好降级文案（实测）；history/reset 端点实测通过
- 评审意见已消化：端点补齐、死代码删除、指引意图加业务实体词拦截、溯源补反向单位变体、金标集 20 题

## 7. 需要你做的事

1. 在项目根目录 `.env` 写入 `DEEPSEEK_API_KEY=sk-你的key`（compose 已透传，不会进 git/镜像）
2. 确认本计划后我继续 #19-22