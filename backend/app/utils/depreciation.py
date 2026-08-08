"""折旧算法（纯函数）。对应设计书 §5.4：直线法、残值 10%、5 年，月折旧=年/12，末期吸收尾差。

W7-8 新增售后回租折旧截断（truncated_schedule / carrying_amount / compute_sale_gain_loss）。
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")
DEFAULT_RESIDUAL_RATE = Decimal("0.10")
DEFAULT_YEARS = 5


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def depreciation_inputs(
    total_original_value: Decimal,
    residual_rate: Decimal = DEFAULT_RESIDUAL_RATE,
    years: int = DEFAULT_YEARS,
) -> dict:
    residual_value = q2(total_original_value * residual_rate)
    depreciable = q2(total_original_value - residual_value)
    annual = q2(depreciable / years)
    monthly = q2(annual / 12)
    return {
        "residual_value": residual_value,
        "depreciable_value": depreciable,
        "annual_depreciation": annual,
        "monthly_depreciation": monthly,
        "months": years * 12,
    }


def monthly_schedule(depreciable: Decimal, months: int = DEFAULT_YEARS * 12) -> list[Decimal]:
    """生成每月折旧额列表，末期吸收尾差使 Σ == depreciable。"""
    base = q2(depreciable / months)
    schedule = [base] * months
    diff = q2(depreciable - sum(schedule))
    schedule[-1] = q2(schedule[-1] + diff)
    return schedule


# ============================ W7-8：售后回租折旧截断 ============================


def elapsed_whole_months(start: date, end: date) -> int:
    """两个日期间的**整月数**（不足一整月的当月不计提）。end <= start → 0。

    回租出售按"已过整月"计提累计折旧：点亮 2026-01-15、出售 2026-03-10 → 2 整月（3 月未满）。
    """
    if end <= start:
        return 0
    total = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        total -= 1  # 当月未满整月
    return max(total, 0)


def truncated_schedule(monthly_depreciation: Decimal, elapsed_months: int) -> list[Decimal]:
    """出售折旧截断：返回前 elapsed_months 期的月折旧额列表。

    **M1 数学修正（审计）**：每期 = q2(monthly_depreciation)，**末期不吸收剩余净值**。
    吸收尾差是 monthly_schedule **全 60 期**让 Σ==depreciable 的模式；若套到截断（N<60），
    末期会一次提完 60-N 个月剩余折旧 → 严重多提、carrying_amount 错误偏低、损益错误偏向亏损。
    截断语义 = "到第 N 月停止"，Σ(truncated) ≈ monthly × N（独立于 depreciable_value）。

    不动 asset.monthly_depreciation（保留原值供审计）；截断通过 end_date=sale_date +
    operation_status='已处置' 落地（leaseback_sale_service）。
    """
    if elapsed_months <= 0:
        return []
    return [q2(monthly_depreciation) for _ in range(elapsed_months)]


def carrying_amount(total_original_value: Decimal, monthly_depreciation: Decimal,
                    elapsed_months: int, residual_value: Decimal | None = None) -> Decimal:
    """出售日**账面价值** = 原值 - 累计折旧。

    **M1**：与 truncated_schedule 解耦——累计折旧 = q2(monthly × 已过整月数)，独立计算；
    不依赖 truncated_schedule 的 Σ（虽然两者数值一致，但语义独立，防未来截断函数改动污染账面）。
    全折旧后（累计 > 原值-残值）不低于 residual_value（floor），避免负账面。
    """
    accumulated = q2(monthly_depreciation * elapsed_months)
    net = q2(total_original_value - accumulated)
    if residual_value is not None and net < residual_value:
        return q2(residual_value)
    return net


def compute_sale_gain_loss(sale_price: Decimal, carrying: Decimal) -> Decimal:
    """出售损益 = 出售价 - 账面价值。正=收益，负=损失（q2 对齐）。"""
    return q2(sale_price - carrying)
