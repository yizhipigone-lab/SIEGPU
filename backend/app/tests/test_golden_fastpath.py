"""金标集 fastpath 层确定性回归（M-B B-2，审计一修正：并入 pytest，无 CI 依赖）。

零 LLM、零 token：golden_set 里 tier=fastpath 的题逐条过 fastpath.match()，
断言意图命中（expect_tools_any 任一）。count/capital 类意图需 db fixture；
guide 类意图 db=None 即可。只断言意图，不断言数据。
"""
import json
from pathlib import Path

import pytest

from app.services.assistant import fastpath

_GOLDEN = Path(__file__).resolve().parents[1] / "services" / "assistant" / "golden_set.json"


def _cases():
    return [c for c in json.loads(_GOLDEN.read_text(encoding="utf-8"))
            if c.get("tier") == "fastpath"]


def test_fastpath_golden_with_db(db):
    """资金/还款/预警/计数类意图（需 db fixture）。"""
    cases = [c for c in _cases() if "资金" in c["q"] or "还款" in c["q"] or "预警" in c["q"] or "订单" in c["q"]]
    assert cases, "金标集缺 fastpath db 类题"
    for c in cases:
        r = fastpath.match(c["q"], db)
        used = [r.intent] if r else []
        expect = c.get("expect_tools_any") or []
        assert r is not None, f"{c['id']}: 快路径未接住（route_miss）"
        assert any(t in used for t in expect), f"{c['id']}: 意图错误 {used} not in {expect}"


def test_fastpath_golden_guide_no_db():
    """纯指引题不需要 db。"""
    r = fastpath.match("点亮是什么意思？", None)
    assert r is not None and r.intent == "guide"