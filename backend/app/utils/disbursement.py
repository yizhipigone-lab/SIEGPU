"""放款达成率（一期 W7-8 §2.4）：批次点亮验收完成度 → 是否达放款阈值。

放款联动（Phase 4）的纯函数：点亮验收完成的设备数 / 批次总设备数 → 百分比。
阈值存 orders.disbursement_threshold_pct（0-100，应用层÷100）。
"""
from decimal import Decimal, ROUND_HALF_UP

_PCT_Q = Decimal("0.01")


def disbursement_completion_pct(lit_count: int, total_count: int) -> Decimal:
    """达阈值百分比（0-100，q2）。

    total ≤ 0 → 0（空批次不算达成，防除零）。返回 Decimal 便于与 threshold 直接比较。
    """
    if total_count <= 0:
        return Decimal("0")
    return (Decimal(lit_count) * Decimal("100") / Decimal(total_count)).quantize(
        _PCT_Q, rounding=ROUND_HALF_UP)


def reached_threshold(lit_count: int, total_count: int, threshold_pct: Decimal) -> bool:
    """便捷判定：达成率是否 >= 阈值（threshold_pct 为 0-100 的百分数）。"""
    if total_count <= 0:
        return False
    return disbursement_completion_pct(lit_count, total_count) >= threshold_pct
