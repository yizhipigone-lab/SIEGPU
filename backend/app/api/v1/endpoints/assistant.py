"""智能助手端点（P0+）：POST /chat（SSE 流式）+ GET /history + POST /reset + POST /feedback。

链路：fastpath 快路径（单次成文）→ 未命中走 agent loop（工具轮 ≤ settings.assistant_max_tool_calls）。
SSE 事件协议（与前端 AssistantDrawer 对齐）：
  data: {"type":"progress","text":"正在查：发票"}   工具轮进度（体验包 #5）
  data: {"type":"delta","text":"..."}               流式正文
  data: {"type":"done","low_confidence":bool,"tools_used":[],"links":[],"message_id":"...","quota_left":int}
  data: {"type":"error","message":"..."}            友好降级（无 key/超配额/LLM 故障）
纪律（修复包 2026-08-27）：
- 配额：agent loop 每一轮的 token 都累计落库（此前只记最后一轮，闸门有洞）。
- 低置信标记只是展示层注解，**不入库**——入库会被模型从历史里学到并模仿格式。
铁律：任何环节失败都走 error 事件收尾，绝不让异常逃出 generator（大脑挂了 ERP 零感知）。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.assistant import engine, fastpath, guardrails, memory, prompts, tools

router = APIRouter()

# 工具/意图 → 中文名（进度行）与跳转页（done.links，体验包 #6；无对应页面不出链接）
TOOL_LABEL = {
    "get_business_board": "经营看板", "get_capital_position": "资金池头寸",
    "search_projects": "项目检索", "get_project_overview": "项目总览",
    "get_workflow_status": "流程进度", "list_due_repayments": "还款计划",
    "get_invoice_status": "发票状态", "list_alerts": "预警扫描",
    "get_reconciliation_diffs": "三流对账", "search_guide": "指引知识库",
    "describe_schema": "数据字典", "query_data": "数据查询",
    "get_entity_counts": "实体计数", "get_order_summary": "订单摘要",
    # fastpath 意图名
    "guide": "指引知识库", "capital": "资金池头寸", "repayment": "还款计划",
    "alerts": "预警扫描", "order_summary": "订单摘要", "entity_counts": "实体计数",
}
TOOL_ROUTES = {
    "get_business_board": ("首页看板", "/"), "get_capital_position": ("资金池", "/capital"),
    "capital": ("资金池", "/capital"), "list_due_repayments": ("金租流程", "/leasing"),
    "repayment": ("金租流程", "/leasing"), "get_invoice_status": ("发票/对账", "/invoices"),
    "get_reconciliation_diffs": ("对账中心", "/reconciliation-center"),
    "search_projects": ("项目总览", "/portfolio"), "get_project_overview": ("项目总览", "/portfolio"),
    "get_workflow_status": ("项目总览", "/portfolio"), "get_order_summary": ("订单", "/orders"),
    "order_summary": ("订单", "/orders"), "list_alerts": ("首页", "/"), "alerts": ("首页", "/"),
}


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    channel: str = Field(default="main", max_length=64)
    page_context: str | None = Field(default=None, max_length=200)


class FeedbackIn(BaseModel):
    message_id: str
    value: str = Field(pattern="^(up|down)$")
    question: str | None = Field(default=None, max_length=2000)  # 👎 时带上问题原文，落缺口表


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _links_for(tools_used: list[str]) -> list[dict]:
    seen, out = set(), []
    for t in tools_used:
        r = TOOL_ROUTES.get(t)
        if r and r[1] not in seen:
            seen.add(r[1])
            out.append({"label": r[0], "route": r[1]})
    return out[:3]


def _stream_answer(messages: list[dict], evidence_text: str):
    """单次流式成文 + 金额溯源标注。final 事件携带 raw_answer（不含低置信标记，供入库）。"""
    parts: list[str] = []
    usage: dict = {}
    for ev in engine.chat_stream(messages):
        if "delta" in ev:
            parts.append(ev["delta"])
            yield ("delta", ev["delta"], None)
        elif ev.get("done"):
            usage = ev.get("usage") or {}
        elif "error" in ev:
            yield ("error", ev["error"], None)
            return
    raw = "".join(parts)
    answer, ok = guardrails.ensure_traced(raw, evidence_text)
    if not ok:
        tail = answer[len(raw):]
        if tail:
            yield ("delta", tail, None)
    yield ("final", None, {"usage": usage, "low_confidence": not ok, "raw_answer": raw})


@router.post("/chat")
def chat(body: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if memory.quota_left(db, user.id) <= 0:
        def _over():
            yield _sse({"type": "error",
                        "message": f"今日对话额度已用完（{settings.assistant_daily_token_quota} tokens），明天再来或找管理员调整。"})
        return StreamingResponse(_over(), media_type="text/event-stream")

    session = memory.get_or_create_session(db, user.id, body.channel, body.page_context)
    memory.save_message(db, session.id, "user", body.question)
    db.commit()

    def gen():
        tools_used: list[str] = []
        answer = ""        # 展示用（含低置信标记）
        raw_answer = ""    # 入库用（不含标记，防模型模仿）
        low_conf = False
        total_tokens = 0
        try:
            fp = fastpath.match(body.question, db)
            if fp is not None:
                tools_used.append(fp.intent)
                yield _sse({"type": "progress", "text": f"快路径：{TOOL_LABEL.get(fp.intent, fp.intent)}"})
                msgs = prompts.compose_data_prompt(body.question, fp.packs)
                for kind, text, meta in _stream_answer(msgs, fp.evidence_text):
                    if kind == "delta":
                        answer += text
                        yield _sse({"type": "delta", "text": text})
                    elif kind == "error":
                        yield _sse({"type": "error", "message": f"助手暂时不可用：{text}"})
                        return
                    else:
                        meta = meta or {}
                        total_tokens += int((meta.get("usage") or {}).get("total_tokens", 0) or 0)
                        low_conf = meta.get("low_confidence", False)
                        raw_answer = meta.get("raw_answer", answer)
            else:
                history = memory.load_history(db, session.id)
                msgs = [{"role": "system", "content": _system_with_context(user, body.page_context)}]
                msgs += history[:-1] if history and history[-1]["content"] == body.question else history
                msgs.append({"role": "user", "content": body.question})
                evidence = ""
                oai_tools = tools.openai_tools()
                for _round in range(settings.assistant_max_tool_calls):
                    r = engine.chat_completion(msgs, tools=oai_tools)
                    # 修复包 #1：每一轮工具调用的 token 都累计，闸门无洞
                    total_tokens += int((r.get("usage") or {}).get("total_tokens", 0) or 0)
                    if not r["success"]:
                        yield _sse({"type": "error",
                                    "message": _friendly_error(r["error_kind"], r["error"])})
                        return
                    msg = r["message"] or {}
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        raw_answer, low_conf = guardrails.ensure_traced(msg.get("content") or "", evidence)
                        answer = raw_answer if low_conf else (msg.get("content") or "")
                        # ensure_traced 返回带标记版本；raw_answer 保持无标记
                        raw_answer = msg.get("content") or ""
                        if answer:
                            yield _sse({"type": "delta", "text": answer})
                        break
                    msgs.append(msg)
                    for c in calls:
                        name = c.get("function", {}).get("name", "")
                        try:
                            args = json.loads(c.get("function", {}).get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        yield _sse({"type": "progress",
                                    "text": f"正在查：{TOOL_LABEL.get(name, name)}"})
                        try:
                            result = tools.call_tool(db, name, args)
                            wrapped = prompts.wrap_data(name, result)
                        except Exception as exc:  # noqa: BLE001 —— 单工具失败标【缺】，不拖死整轮
                            wrapped = prompts.wrap_data(name, {"error": f"工具执行失败: {str(exc)[:120]}"})
                        tools_used.append(name)
                        evidence += wrapped + "\n"
                        msgs.append({"role": "tool", "tool_call_id": c.get("id", ""),
                                     "content": wrapped})
                else:
                    yield _sse({"type": "error",
                                "message": "这个问题需要的查询轮数超过上限，请把问题拆小一点再问。"})
                    return
                if not answer:
                    yield _sse({"type": "progress", "text": "正在成文…"})
                    for kind, text, meta in _stream_answer(msgs + [
                            {"role": "user", "content": "请基于以上数据回答我最初的问题。"}],
                            evidence):
                        if kind == "delta":
                            answer += text
                            yield _sse({"type": "delta", "text": text})
                        elif kind == "error":
                            yield _sse({"type": "error", "message": f"助手暂时不可用：{text}"})
                            return
                        else:
                            meta = meta or {}
                            total_tokens += int((meta.get("usage") or {}).get("total_tokens", 0) or 0)
                            low_conf = meta.get("low_confidence", False)
                            raw_answer = meta.get("raw_answer", answer)
            saved = memory.save_message(db, session.id, "assistant", raw_answer or answer,
                                        tool_calls={"tools": tools_used} if tools_used else None,
                                        tokens_used=total_tokens)
            db.commit()
            yield _sse({"type": "done", "low_confidence": low_conf,
                        "tools_used": tools_used, "links": _links_for(tools_used),
                        "message_id": str(saved.id),
                        "quota_left": memory.quota_left(db, user.id)})
        except Exception as exc:  # noqa: BLE001 —— 铁律：异常绝不逃出 generator
            yield _sse({"type": "error", "message": f"助手内部错误（已降级，不影响系统）：{str(exc)[:120]}"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _system_with_context(user: User, page_context: str | None) -> str:
    role_cn = {"FINANCE_DIRECTOR": "财务总监", "PROCUREMENT": "采购对接人",
               "DELIVERY": "交付负责人", "FINANCE_STAFF": "财务专员", "ADMIN": "管理员"}.get(user.role, user.role)
    ctx = f"\n\n## 当前对话上下文\n用户角色：{role_cn}"
    if page_context:
        ctx += f"\n用户当前所在页面：{page_context}（用户说「这个页面/这里」时指它）"
    return prompts.SYSTEM_PROMPT + ctx


def _friendly_error(kind: str | None, detail: str | None) -> str:
    return {
        "NO_API_KEY": "智能助手未配置 API Key，请联系管理员在 .env 配置 DEEPSEEK_API_KEY。",
        "QUOTA": "LLM 服务配额已耗尽，请稍后再试或联系管理员。",
        "AUTH": "LLM 服务鉴权失败，请联系管理员检查 API Key。",
        "NETWORK": "网络异常，助手暂时不可用，请稍后重试。",
    }.get(kind or "", f"助手暂时不可用：{(detail or '')[:100]}")


@router.get("/history")
def history(channel: str = "main", db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """当前 channel 的最近消息（打开侧边栏时回放；含 message_id 供反馈）。"""
    s = memory.get_or_create_session(db, user.id, channel)
    msgs = memory.load_history_full(db, s.id, rounds=25)
    return {"session_id": str(s.id), "messages": msgs,
            "quota_left": memory.quota_left(db, user.id)}


@router.post("/reset")
def reset(channel: str = "main", db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    """新对话：软删当前 channel 会话线。"""
    cleared = memory.reset_session(db, user.id, channel)
    db.commit()
    return {"cleared": cleared}


@router.post("/feedback")
def feedback(body: FeedbackIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """👍/👎 反馈（体验包 #7）：👎 同时落问题缺口表——缺口驱动后续补工具/补 KB。"""
    from app.models.assistant import AssistantGap, AssistantMessage
    msg = db.get(AssistantMessage, body.message_id)
    if not msg:
        return {"ok": False}
    msg.feedback = body.value
    if body.value == "down":
        db.add(AssistantGap(user_id=user.id, question=body.question or "",
                            answer_head=(msg.content or "")[:200],
                            tools_used=(msg.tool_calls or {}).get("tools"),
                            reason="user_downvote"))
    db.commit()
    return {"ok": True}