"""智能助手端点（智能层版）：chat(SSE) + history + reset + feedback + confirm + cancel。

M-A 接线：agent 分支注入认知（<data> 包裹、≤1500 字符预算）→ cognition_used 记入
assistant_messages.tool_calls（👎 衰减的归因前提）→ 自动别名捕获（唯一命中+非全名+非代词）。
M-C 接线：写工具 dry_run 返回 card → SSE card 事件下发；确认执行只走 /confirm（LLM 无执行通道）。
SSE 事件协议：progress / delta / card / done / error（详见各 yield）。
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

TOOL_LABEL = {
    "get_business_board": "经营看板", "get_capital_position": "资金池头寸",
    "search_projects": "项目检索", "get_project_overview": "项目总览",
    "get_workflow_status": "流程进度", "list_due_repayments": "还款计划",
    "get_invoice_status": "发票状态", "list_alerts": "预警扫描",
    "get_reconciliation_diffs": "三流对账", "search_guide": "指引知识库",
    "describe_schema": "数据字典", "query_data": "数据查询",
    "get_entity_counts": "实体计数", "get_order_summary": "订单摘要",
    "save_cognition": "保存认知", "list_cognition": "查看认知", "forget_cognition": "忘掉认知",
    "request_record_income": "回款预览", "request_draft_billing": "计费预览",
    "request_advance_step": "流程预览", "request_allocate_funds": "调配预览",
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
    question: str | None = Field(default=None, max_length=2000)


class TokenIn(BaseModel):
    token_id: str


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
    """单次流式成文 + 金额溯源标注。final 携带 raw_answer（不含低置信标记，供入库）。"""
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


def _try_auto_alias(db, user_id, question: str, search_names: list[str]) -> None:
    """自动别名捕获（克制）：唯一命中 + 名称≠全名 + 长度≥2 + 无代词黑名单。失败静默。"""
    try:
        for name in set(search_names):
            n = (name or "").strip()
            if not n or len(n) < 2 or any(d in n for d in memory._ALIAS_DENY):
                continue
            hits = tools.search_projects(db, n)
            if len(hits) == 1 and hits[0]["name"] != n and n in question:
                memory.save_cognition(db, user_id, n, f"指项目 {hits[0]['name']}",
                                      "entity_alias", source="auto")
    except Exception:  # noqa: BLE001 —— 自动捕获失败绝不影响主流程
        pass


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
        answer = raw_answer = ""
        low_conf = False
        total_tokens = 0
        cognition_ids: list[str] = []
        cards: list[dict] = []
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
                # —— 认知召回 + 注入（M-A；预算内 <data> 包裹）——
                hits = memory.relevant_cognition(db, user.id, body.question) if settings.assistant_cognition_enabled else []
                cognition_ids = [h["id"] for h in hits]
                cog_block = memory.format_cognition_block(hits)
                history = memory.load_history(db, session.id)
                msgs = [{"role": "system", "content": _system_with_context(user, body.page_context) + cog_block}]
                msgs += history[:-1] if history and history[-1]["content"] == body.question else history
                msgs.append({"role": "user", "content": body.question})
                evidence = ""
                search_names: list[str] = []
                oai_tools = tools.openai_tools()
                for _round in range(settings.assistant_max_tool_calls):
                    r = engine.chat_completion(msgs, tools=oai_tools)
                    total_tokens += int((r.get("usage") or {}).get("total_tokens", 0) or 0)
                    if not r["success"]:
                        yield _sse({"type": "error", "message": _friendly_error(r["error_kind"], r["error"])})
                        return
                    msg = r["message"] or {}
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        raw_answer, low_conf = guardrails.ensure_traced(msg.get("content") or "", evidence)
                        answer = raw_answer if low_conf else (msg.get("content") or "")
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
                        yield _sse({"type": "progress", "text": f"正在查：{TOOL_LABEL.get(name, name)}"})
                        result = None
                        try:
                            result = tools.call_tool(db, name, args, user=user)
                            wrapped = prompts.wrap_data(name, result)
                        except Exception as exc:  # noqa: BLE001 —— 单工具失败标【缺】，不拖死整轮
                            wrapped = prompts.wrap_data(name, {"error": f"工具执行失败: {str(exc)[:120]}"})
                        tools_used.append(name)
                        if name == "search_projects":
                            search_names.append(str(args.get("name", "")))
                        # 写 dry-run 结果带 card → SSE card 事件（前端渲染确认卡）
                        if isinstance(result, dict) and isinstance(result.get("card"), dict):
                            cards.append(result["card"])
                            yield _sse({"type": "card", "card": result["card"]})
                            db.commit()  # 卡片下发即提交令牌，确认端点另起事务
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
                # 自动别名捕获（克制；失败静默）
                if settings.assistant_cognition_enabled and search_names:
                    _try_auto_alias(db, user.id, body.question, search_names)
                # 认知使用强化（M1 近似：注入即视为使用）
                if cognition_ids:
                    memory.note_cognition_used(db, cognition_ids)
            saved = memory.save_message(db, session.id, "assistant", raw_answer or answer,
                                        tool_calls={"tools": tools_used,
                                                    "cognition_used": cognition_ids,
                                                    "cards": [c.get("token_id") for c in cards]} if (tools_used or cognition_ids or cards) else None,
                                        tokens_used=total_tokens)
            db.commit()
            yield _sse({"type": "done", "low_confidence": low_conf,
                        "tools_used": tools_used, "links": _links_for(tools_used),
                        "message_id": str(saved.id), "cards": cards,
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
    s = memory.get_or_create_session(db, user.id, channel)
    msgs = memory.load_history_full(db, s.id, rounds=25)
    return {"session_id": str(s.id), "messages": msgs,
            "quota_left": memory.quota_left(db, user.id)}


@router.post("/reset")
def reset(channel: str = "main", db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    cleared = memory.reset_session(db, user.id, channel)
    db.commit()
    return {"cleared": cleared}


@router.post("/feedback")
def feedback(body: FeedbackIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """👍/👎；👎 时同步衰减本条回答用到的认知（归因：tool_calls.cognition_used，审计二 D16）。"""
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
        memory.decay_cognition_for_message(db, msg)
    db.commit()
    return {"ok": True}


@router.post("/confirm")
def confirm(body: TokenIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """确认执行写操作（LLM 无权触达的唯一执行通道）。"""
    from app.services.assistant import writes
    r = writes.execute(db, user, body.token_id)
    db.commit()
    return r


@router.post("/cancel")
def cancel(body: TokenIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    from app.services.assistant import writes
    r = writes.cancel(db, user, body.token_id)
    db.commit()
    return r