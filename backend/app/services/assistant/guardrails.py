"""金额溯源校验（ERP 版 VERA evidence.py，财务系统对幻觉零容忍）。

启发式（宁可宽松放过，不搞复杂 NLP，与 VERA 同哲学）：
- 抽取回答中的「大数字」（≥1000 或带小数/万元单位的金额样数字）；
- 在本轮工具返回的序列化文本里找等价写法（原值、千分位、去小数）；
- 找不到不拦截回答，追加低置信标记让用户看得见——静默放行是撒谎。
"""
from __future__ import annotations

import re

# 金额样数字：千分位、带小数、≥4 位整数、或「N万/N亿」；排除年份与期数小数字
_NUM_RE = re.compile(
    r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?|\d+\.\d+)(?![\d%])"
    r"|(?<![\d.])(\d+(?:\.\d+)?)(?=\s*[万亿]元?)"
)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

LOW_CONFIDENCE_TAG = (
    "\n\n> ⚠️ 低置信：本回答中的部分数字未能溯源到系统数据，请到对应页面核实后再使用。"
)


def _variants(num: str) -> set[str]:
    """一个数字的等价写法：原样、去千分位、去小数点、整数值。"""
    raw = num.replace(",", "")
    out = {num, raw}
    try:
        f = float(raw)
        out.add(f"{f:.2f}")
        out.add(f"{f:.1f}")
        if f == int(f):
            out.add(str(int(f)))
        # 万元/亿元 换算（回答写 12.5万，工具返回 125000）
        out.add(f"{f * 10000:.2f}".rstrip("0").rstrip("."))
        out.add(f"{f * 100000000:.2f}".rstrip("0").rstrip("."))
        # 评审修正（2026-08-27）反向也查：回答写 125000，工具返回 12.5（万）
        out.add(f"{f / 10000:.4f}".rstrip("0").rstrip("."))
        out.add(f"{f / 100000000:.4f}".rstrip("0").rstrip("."))
    except ValueError:
        pass
    return {v for v in out if v}


def _amount_shaped(token: str, text: str, end: int) -> bool:
    """金额样数字才校验（2026-08-27 误报修正）：带千分位/小数、≥6 位、或紧跟 万/亿/元。
    4-5 位裸数字（项目编号 5090、台数 1372）不校验——那是编号不是金额。"""
    plain = token.replace(",", "")
    if "," in token or "." in token:
        return True
    if len(plain.split(".")[0]) >= 6:
        return True
    tail = text[end:end + 2]
    return tail.startswith(("万", "亿", "元"))


def extract_numbers(text: str) -> list[str]:
    nums = []
    for m in _NUM_RE.finditer(text or ""):
        token = m.group(0)
        plain = token.replace(",", "")
        if _YEAR_RE.match(plain.split(".")[0]):
            continue  # 年份不是金额
        if not _amount_shaped(token, text, m.end()):
            continue  # 编号/小数字不参与金额溯源
        nums.append(token)
    return nums


def untraceable_numbers(answer: str, evidence_text: str) -> list[str]:
    """回答里在证据文本中找不到等价写法的数字列表。evidence 为空 → 全部算未溯源。"""
    bad = []
    for token in extract_numbers(answer):
        if not any(v in evidence_text for v in _variants(token)):
            bad.append(token)
    return bad


def ensure_traced(answer: str, evidence_text: str) -> tuple[str, bool]:
    """(标注后回答, 是否全部可溯源)。缺失 → 追加低置信标记。"""
    if not (answer or "").strip():
        return answer, True
    if untraceable_numbers(answer, evidence_text):
        return answer + LOW_CONFIDENCE_TAG, False
    return answer, True