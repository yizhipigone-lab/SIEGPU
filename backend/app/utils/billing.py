"""计费/收入确认算法（纯函数）。

对应设计书 §5.3：点亮日为计费起点，首月按剩余天数（含点亮当日）比例计，之后整月；价税分离。
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def split_tax(amount_incl: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal]:
    """含税金额价税分离：返回 (不含税, 税额)，满足 ex + tax == amount_incl（税额吸收尾差）。"""
    ex = q2(amount_incl / (Decimal(1) + tax_rate))
    return ex, q2(amount_incl - ex)


def days_in_month(d: date) -> int:
    return monthrange(d.year, d.month)[1]


def first_month_amount(monthly_rent_incl: Decimal, light_on: date) -> Decimal:
    """首月按 (当月剩余天数 / 当月总天数) 比例计，剩余天数含点亮当日。"""
    dim = days_in_month(light_on)
    remaining = dim - light_on.day + 1
    return q2(monthly_rent_incl * Decimal(remaining) / Decimal(dim))


def billing_amount(monthly_rent_incl: Decimal, period_index: int, light_on: date) -> Decimal:
    """period_index=1 首月按比例；其余整月。"""
    if period_index < 1:
        raise ValueError("period_index 必须 >= 1")
    if period_index == 1:
        return first_month_amount(monthly_rent_incl, light_on)
    return q2(monthly_rent_incl)
