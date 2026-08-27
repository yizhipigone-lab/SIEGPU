"""金标集回归评测（VERA eval.py 移植）：逐题问大脑，must_contain 正则（| 分隔多选一）全中算过。

用法（容器内，需真实 DEEPSEEK_API_KEY）：
    python -m app.services.assistant.eval [--limit 5]
无 key 时如实报告「不可评估」，不伪造结果（VERA 同款纪律）。
fastpath 题额外校验实际走的意图/工具是否符合预期。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_GOLDEN = Path(__file__).resolve().parent / "golden_set.json"
PASS_THRESHOLD = 0.8


def _hit(pattern: str, text: str) -> bool:
    """'A|B|C' 任一子模式命中即算过。"""
    return any(re.search(p, text or "") for p in pattern.split("|"))


def run(limit: int | None = None) -> dict:
    from app.core.db import SessionLocal
    from app.services.assistant import engine, fastpath, guardrails, prompts, tools

    if not engine.available():
        return {"evaluable": False, "reason": "未配置 DEEPSEEK_API_KEY，不可评估（不伪造结果）"}

    cases = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    if limit:
        cases = cases[:limit]
    results = []
    db = SessionLocal()
    try:
        for c in cases:
            q = c["q"]
            answer, used = "", []
            fp = fastpath.match(q, db)
            if fp is not None:
                used.append(fp.intent)
                r = engine.chat_completion(prompts.compose_data_prompt(q, fp.packs))
                if r["success"] and r["message"]:
                    answer = r["message"].get("content") or ""
                    answer, _ = guardrails.ensure_traced(answer, fp.evidence_text)
            else:
                msgs = [{"role": "system", "content": prompts.SYSTEM_PROMPT},
                        {"role": "user", "content": q}]
                evidence = ""
                for _ in range(4):  # 评测轮数收紧，省钱
                    r = engine.chat_completion(msgs, tools=tools.openai_tools())
                    if not r["success"]:
                        break
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
                            res = tools.call_tool(db, name, args)
                        except Exception as exc:  # noqa: BLE001
                            res = {"error": str(exc)[:120]}
                        used.append(name)
                        msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                     "content": prompts.wrap_data(name, res)})
            text_ok = all(_hit(p, answer) for p in c.get("must_contain", []))
            tool_expect = c.get("expect_tools_any")
            tool_ok = True if not tool_expect else any(t in used for t in tool_expect)
            results.append({"id": c["id"], "passed": text_ok and tool_ok,
                            "answer_head": answer[:120], "tools": used,
                            "text_ok": text_ok, "tool_ok": tool_ok})
    finally:
        db.close()
    passed = sum(1 for r in results if r["passed"])
    return {"evaluable": True, "total": len(results), "passed": passed,
            "pass_rate": round(passed / len(results), 3) if results else 0,
            "threshold": PASS_THRESHOLD,
            "gate": (passed / len(results)) >= PASS_THRESHOLD if results else False,
            "results": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    report = run(args.limit)
    if not report["evaluable"]:
        print(report["reason"])
        return 2
    for r in report["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['id']}  tools={r['tools']}  {r['answer_head']}")
    print(f"\n通过率 {report['passed']}/{report['total']} = {report['pass_rate']}"
          f"（闸口 ≥{report['threshold']}）→ {'达标' if report['gate'] else '未达标'}")
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    sys.exit(main())