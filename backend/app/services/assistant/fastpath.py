"""高频意图快路径（VERA fastpath.py 移植）：跳过 agent 多轮循环，一次取数 + 单次成文。

意图识别刻意保守：宁可漏判走 agent loop（只是慢），不可误判走错路（答错数）。
任何一步取数异常 → 返回 None，调用方回落 agent loop（松耦合）。
2026-08-27 P0 四类意图：资金头寸 / 逾期与临期还款 / 当前预警 / 新手流程指引（KB）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

# —— 意图词表（保守：只收指向明确的词）——
_CAPITAL_KW = ("资金池", "头寸", "可调余额", "资金余额", "池子")
_REPAY_KW = ("逾期", "临期", "还款计划", "待还", "到期还")
_ALERT_KW = ("预警", "告警", "提醒", "风险提示", "异常")
_COUNT_VERB = ("多少", "几张", "几个", "多少张", "总数", "数量", "有几")
_COUNT_ORDER_KW = ("订单", "采购订单", "销售订单")
# 计数快路径的失格词（2026-08-27 实测教训）：「多少钱」是求和不是计数；
# 「的/下/里」意味着带限定条件（某项目的设备/应收方向的发票），裸计数答非所问。
# 失格 → 回落 agent loop，由 query_data 组条件/聚合自己查（宁慢勿错）。
_COUNT_DISQUALIFY = ("钱", "金额", "的", "下", "里", "其中", "分别", "各")
_GUIDE_KW = ("怎么", "如何", "是什么", "什么意思", "区别", "怎么做", "在哪操作",
             "哪个菜单", "流程", "步骤", "月结", "新手指引")
# 评审修正（2026-08-27）：指引词过于宽泛——「怎么登记回款」是业务操作问题不是指引。
# 命中指引词的同时若含业务实体词，不走 KB 快路径，回落 agent loop（由 search_guide 工具按需介入）。
_BIZ_ENTITY_KW = ("资金", "还款", "回款", "发票", "合同", "项目", "设备", "计费",
                  "预警", "对账", "池", "放款", "逾期")


@dataclass
class FastpathResult:
    intent: str
    packs: list[tuple[str, Any]] = field(default_factory=list)  # (工具名, 数据包)
    evidence_text: str = ""                                     # 溯源校验用的证据文本


def _safe(fn, *args, **kwargs):
    """取数独立容错：单个源挂了返回 None（上层回落），不拖死整链路（VERA data_tools 同款）。"""
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        return None


def match(question: str, db: Session) -> FastpathResult | None:
    """命中意图 → FastpathResult；未命中/取数失败 → None（走 agent loop）。"""
    q = (question or "").strip()
    if not q:
        return None
    from app.services.assistant import kb, prompts, tools  # 延迟导入防循环

    # 1. 流程指引类（KB）：先判——「怎么/是什么」类问题不该去查业务数据
    if any(k in q for k in _GUIDE_KW) and not any(k in q for k in _BIZ_ENTITY_KW):
        hits = kb.search(q, top_k=3)
        if hits and hits[0]["score"] >= 3.0:  # 必须有策展关键词命中，纯 bigram 不够格
            packs = [("guide_kb", hits)]
            return FastpathResult("guide", packs, prompts.wrap_data("guide_kb", hits))

    # 2. 资金头寸
    if any(k in q for k in _CAPITAL_KW):
        data = _safe(tools.get_capital_position, db)
        if data:
            return FastpathResult("capital", [("capital_position", data)],
                                  prompts.wrap_data("capital_position", data))

    # 3. 逾期/临期还款
    if any(k in q for k in _REPAY_KW):
        data = _safe(tools.list_due_repayments, db)
        if data is not None:
            return FastpathResult("repayment", [("due_repayments", data)],
                                  prompts.wrap_data("due_repayments", data))

    # 3.5 计数类（「有多少张采购订单」——2026-08-27 用户反馈：最朴素的问题必须秒回）
    if any(v in q for v in _COUNT_VERB) and not any(d in q for d in _COUNT_DISQUALIFY):
        if any(k in q for k in _COUNT_ORDER_KW):
            data = _safe(tools.get_order_summary, db)
            if data:
                return FastpathResult("order_summary", [("order_summary", data)],
                                      prompts.wrap_data("order_summary", data))
        else:
            data = _safe(tools.get_entity_counts, db)
            if data:
                return FastpathResult("entity_counts", [("entity_counts", data)],
                                      prompts.wrap_data("entity_counts", data))

    # 4. 当前预警
    if any(k in q for k in _ALERT_KW):
        data = _safe(tools.list_alerts, db)
        if data is not None:
            return FastpathResult("alerts", [("alerts", data)],
                                  prompts.wrap_data("alerts", data))

    return None