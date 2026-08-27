"""智能助手（对话大脑）服务包（2026-08-27 P0，参考 VERA brain/ 架构）。

模块分工：
- engine.py     DeepSeek HTTP 调用：超时/成本闸门/瞬断一次重试/失败不抛异常
- tools.py      只读工具层：封装现有 services，LLM 绝不直接碰 SQL
- fastpath.py   高频意图快路径：跳过 agent 循环，一次取数 + 单次成文
- memory.py     会话管理：channel→session，最近 N 轮历史 + 日配额统计
- prompts.py    system prompt + 取数结果包装（数据非指令红线）
- guardrails.py 金额溯源校验：回答里的金额必须能在工具返回中找到，否则标低置信
- kb.py         新手流程指引知识库 + 轻量检索
- eval.py       金标集回归评测（不造假：无 API key 如实报不可评估）
"""