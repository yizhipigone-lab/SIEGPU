"""DeepSeek HTTP 引擎（VERA claude_cli.py 纪律的 HTTP 版）。

保留的四条铁律：
1. 失败一律返回结构化 dict（success=False），不抛异常——大脑挂了，ERP 零感知。
2. 超时必死：httpx timeout 到点即断，不留悬挂请求。
3. 成本硬闸门：单轮 max_tool_calls 限制 agent 循环轮数（在 memory/agent loop 侧执行）；
   429/配额/鉴权错误绝不重试（重试无意义且烧配额）。
4. 瞬断网络错误（connection reset / 5xx / overloaded）自动重试一次，只一次——
   防循环抖动烧 token。
DeepSeek 走 OpenAI 兼容协议：POST {base}/chat/completions，支持 tools 与 stream。
"""
from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import httpx

from app.core.config import settings

# 瞬断特征（VERA 同款清单；注意不含 429/rate limit——那是配额耗尽，重试无意义）
_TRANSIENT_PATTERNS = (
    "connection closed", "connection reset", "econnreset", "etimedout",
    "socket hang up", "fetch failed", "network error", "overloaded",
    "502", "503", "504",
)


def _is_transient(status: int | None, err_text: str) -> bool:
    if status in (502, 503, 504, 529):
        return True
    return any(p in (err_text or "").lower() for p in _TRANSIENT_PATTERNS)


def available() -> bool:
    """API key 是否已配置；未配置时助手如实报不可用，不伪造回答。"""
    return bool(settings.deepseek_api_key)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json"}


def chat_completion(messages: list[dict], *, tools: list[dict] | None = None,
                    max_tokens: int = 2048, _retried: bool = False) -> dict[str, Any]:
    """非流式补全（工具轮用）。返回 {success, message|None, usage, error_kind, error}。"""
    if not available():
        return {"success": False, "error_kind": "NO_API_KEY",
                "error": "未配置 DEEPSEEK_API_KEY，智能助手不可用", "message": None, "usage": {}}
    body: dict[str, Any] = {
        "model": settings.assistant_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,  # ERP 问答要稳不要花
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    try:
        with httpx.Client(timeout=settings.assistant_timeout_seconds) as client:
            r = client.post(f"{settings.deepseek_base_url}/chat/completions",
                            headers=_headers(), json=body)
        if r.status_code != 200:
            if _is_transient(r.status_code, r.text) and not _retried:
                return chat_completion(messages, tools=tools, max_tokens=max_tokens, _retried=True)
            kind = "QUOTA" if r.status_code == 429 else ("AUTH" if r.status_code in (401, 403) else "PROVIDER")
            return {"success": False, "error_kind": kind,
                    "error": f"LLM 服务返回 {r.status_code}: {r.text[:200]}",
                    "message": None, "usage": {}}
        data = r.json()
        return {"success": True, "message": data["choices"][0]["message"],
                "usage": data.get("usage", {}), "error_kind": None, "error": None}
    except httpx.HTTPError as exc:
        if _is_transient(None, str(exc)) and not _retried:
            return chat_completion(messages, tools=tools, max_tokens=max_tokens, _retried=True)
        return {"success": False, "error_kind": "NETWORK", "error": str(exc)[:300],
                "message": None, "usage": {}}
    except Exception as exc:  # noqa: BLE001 —— 铁律1：任何意外都不许炸主系统
        return {"success": False, "error_kind": "UNKNOWN", "error": str(exc)[:300],
                "message": None, "usage": {}}


def chat_stream(messages: list[dict], *, max_tokens: int = 2048) -> Generator[dict[str, Any], None, None]:
    """流式补全（最终成文用）。逐 yield {"delta": str}；结尾 {"done": True, "usage": {...}}；
    失败 yield 单个 {"error_kind": ..., "error": ...} 后结束——同样不抛异常。"""
    if not available():
        yield {"error_kind": "NO_API_KEY", "error": "未配置 DEEPSEEK_API_KEY，智能助手不可用"}
        return
    body = {
        "model": settings.assistant_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    try:
        with httpx.Client(timeout=settings.assistant_timeout_seconds) as client:
            with client.stream("POST", f"{settings.deepseek_base_url}/chat/completions",
                               headers=_headers(), json=body) as r:
                if r.status_code != 200:
                    r.read()
                    kind = "QUOTA" if r.status_code == 429 else ("AUTH" if r.status_code in (401, 403) else "PROVIDER")
                    yield {"error_kind": kind, "error": f"LLM 服务返回 {r.status_code}: {r.text[:200]}"}
                    return
                for line in r.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue  # 半行/心跳，跳过
                    if chunk.get("usage"):
                        yield {"done": True, "usage": chunk["usage"]}
                        return  # 真实用量已上报，直接收尾——避免末尾兜底 yield 把它覆盖成 {}
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield {"delta": delta}
        yield {"done": True, "usage": {}}
    except Exception as exc:  # noqa: BLE001 —— 同上，流中途断也按结构化错误收尾
        yield {"error_kind": "NETWORK", "error": str(exc)[:300]}