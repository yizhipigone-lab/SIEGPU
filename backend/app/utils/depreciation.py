"""折旧算法（纯函数）。对应设计书 §5.4：直线法、残值 10%、5 年，月折旧=年/12，末期吸收尾差。"""
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
