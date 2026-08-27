"""金标集回归评测（M-B 升级版）：分层执行 + 失败归因 + 报告落盘 + 闸口退出码。

用法（容器内，需真实 DEEPSEEK_API_KEY）：
    python -m app.services.assistant.eval [--tier all|fastpath|agent|refuse|hallucination] [--limit 5]
- 每题记录 passed / 耗时ms / token / 失败类别（route_miss / intent_miss / tool_miss / text_miss）；
- 报告落盘 backend/output/assistant_eval/eval_<ts>.json（目录运行时创建）；
- 闸口：总通过率 < 80% → 退出码 1（供流水线判定）；
- 无 key 如实报「不可评估」，不伪造结果（VERA 纪律）。
- 防过拟合纪律（审计二 D15）：修一题必须同步加变体题。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

_GOLDEN = Path(__file__).resolve().parent / "golden_set.json"
_REPORT_DIR = Path(__file__).resolve().parents[3] / "output" / "assistant_eval"
PASS_THRESHOLD = 0.8
TIER_GATES = {"fastpath": 0.95, "refuse": 0.90, "hallucination": 0.90, "agent": 0.75}


def _hit(pattern: str, text: str) -> bool:
    return any(re.search(p, text or "") for p in pattern.split("|"))


def _categorize(c: dict, used: list[str], answer: str) -> tuple[bool, str]:
    """(passed, 失败类别)。类别优先级：路由 > 工具 > 文本。"""
    tier = c.get("tier", "agent")
    if tier == "fastpath":
        expect = c.get("expect_tools_any") or []
        if not used:
            return False, "route_miss"          # 快路径没接住，落到 agent——对本层就是失败
        if expect and not any(t in used for t in expect):
            return False, "intent_miss"         # 接住了但意图错了
    else:
        expect = c.get("expect_tools_any")
        if expect and not any(t in used for t in expect):
            return False, "tool_miss"
    ok = all(_hit(p, answer) for p in c.get("must_contain", []))
    none_expect = c.get("expect_tools_none") or []
    if ok and none_expect and any(t in used for t in none_expect):
        return False, "tool_miss"               # 用了不该用的工具（如认知召回题却去 search_projects）
    return ok, ("" if ok else "text_miss")


def run(tier: str = "all", limit: int | None = None) -> dict:
    from app.core.db import SessionLocal
    from app.services.assistant import engine, fastpath, guardrails, prompts, tools

    if not engine.available():
        return {"evaluable": False, "reason": "未配置 DEEPSEEK_API_KEY，不可评估（不伪造结果）"}

    cases = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    if tier != "all":
        cases = [c for c in cases if c.get("tier") == tier]
    # 写开关关闭时跳过依赖写工具的题（不计入分母，不伪造通过）
    from app.services.assistant import writes
    if not writes.enabled_actions():
        cases = [c for c in cases if not c.get("requires_writes")]
    if limit:
        cases = cases[:limit]
    results, db = [], SessionLocal()
    total_tokens = 0
    # eval 专用用户（认知类题需要真实 user 归属；复用固定账号避免重复建行）
    from app.models.user import User as _U
    from sqlalchemy import select as _s
    ev_user = db.execute(_s(_U).where(_U.username == "eval_bot")).scalars().first()
    if not ev_user:
        ev_user = _U(username="eval_bot", display_name="评测", password_hash="x", role="ADMIN", active=True)
        db.add(ev_user)
        db.commit()
    try:
        for i, c in enumerate(cases):
            if i:
                time.sleep(2.0)  # 题间限速：防连续全量跑触发 provider 分钟级限流（B-3 实测教训）
            q, t0 = c["q"], time.monotonic()
            answer, used = "", []
            fp = fastpath.match(q, db)
            if fp is not None:
                used.append(fp.intent)
                r = engine.chat_completion(prompts.compose_data_prompt(q, fp.packs))
                if r["success"] and r["message"]:
                    total_tokens += int((r.get("usage") or {}).get("total_tokens", 0) or 0)
                    answer = r["message"].get("content") or ""
                    answer, _ = guardrails.ensure_traced(answer, fp.evidence_text)
            else:
                msgs = [{"role": "system", "content": prompts.SYSTEM_PROMPT},
                        {"role": "user", "content": q}]
                evidence = ""
                for _ in range(5):  # 评测轮数（B-3 修正：4→5，endpoint 同款 8 上限内收紧）
                    r = engine.chat_completion(msgs, tools=tools.openai_tools())
                    if not r["success"]:
                        answer = f"[ENGINE_ERROR]{r.get('error_kind')}"
                        break
                    total_tokens += int((r.get("usage") or {}).get("total_tokens", 0) or 0)
                    msg = r["message"] or {}
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        answer = msg.get("content") or ""
                        break
                    msgs.append(msg)
                    for tc in calls:
                        name = tc.get("function", {}).get("name", "")
                        try:
                            args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                            res = tools.call_tool(db, name, args, user=ev_user)
                        except Exception as exc:  # noqa: BLE001
                            res = {"error": str(exc)[:120]}
                        used.append(name)
                        msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                     "content": prompts.wrap_data(name, res)})
                if not answer and msgs and msgs[-1]["role"] == "tool":
                    # 工具轮耗尽仍无成文 → 强制最终成文（endpoint 同款兜底，防 text_miss 假失败）
                    r2 = engine.chat_completion(msgs + [
                        {"role": "user", "content": "请基于以上数据回答我最初的问题。"}])
                    if r2["success"] and r2["message"]:
                        total_tokens += int((r2.get("usage") or {}).get("total_tokens", 0) or 0)
                        answer = r2["message"].get("content") or ""
            passed, category = _categorize(c, used, answer)
            results.append({"id": c["id"], "tier": c.get("tier"), "passed": passed,
                            "category": category or None, "latency_ms": int((time.monotonic() - t0) * 1000),
                            "answer_head": answer[:120], "tools": used})
    finally:
        db.close()

    passed = sum(1 for r in results if r["passed"])
    by_tier: dict[str, dict] = {}
    for r in results:
        g = by_tier.setdefault(r["tier"], {"total": 0, "passed": 0})
        g["total"] += 1
        g["passed"] += bool(r["passed"])
    for k, g in by_tier.items():
        g["pass_rate"] = round(g["passed"] / g["total"], 3) if g["total"] else 0
    report = {
        "evaluable": True, "generated_at": dt.datetime.now().isoformat(),
        "tier_filter": tier, "total": len(results), "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0,
        "threshold": PASS_THRESHOLD,
        "gate": bool(results) and passed / len(results) >= PASS_THRESHOLD,
        "tier_gates": {k: {"pass_rate": v["pass_rate"], "gate": v["pass_rate"] >= TIER_GATES.get(k, 0.75)}
                       for k, v in by_tier.items()},
        "total_tokens": total_tokens,
        "results": results,
    }
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    (_REPORT_DIR / f"eval_{ts}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    report["report_path"] = str(_REPORT_DIR / f"eval_{ts}.json")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="all",
                    choices=["all", "fastpath", "agent", "refuse", "hallucination"])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    report = run(args.tier, args.limit)
    if not report["evaluable"]:
        print(report["reason"])
        return 2
    for r in report["results"]:
        mark = "PASS" if r["passed"] else f"FAIL({r['category']})"
        print(f"[{mark}] {r['id']} tier={r['tier']} {r['latency_ms']}ms tools={r['tools']}")
    print(f"\n总通过率 {report['passed']}/{report['total']} = {report['pass_rate']}"
          f"（闸口 ≥{report['threshold']}）→ {'达标' if report['gate'] else '未达标'}")
    for k, v in report["tier_gates"].items():
        print(f"  {k}: {v['pass_rate']} (闸口 {'达标' if v['gate'] else '未达标'})")
    print(f"token 消耗: {report['total_tokens']} | 报告: {report['report_path']}")
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    sys.exit(main())