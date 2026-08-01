"""金租还款计划生成（纯函数）。对应设计书 §5.5：放款时按 actual_disbursement_amount / annual_rate /
term_periods / payment_freq / repayment_method 自动生成 N 期；支持等额本息/等额本金，末期吸收尾差。"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")
FREQS_PER_YEAR = {"月": 12, "季": 4, "半年": 2}


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def add_months(d: date, months: int) -> date:
    """加 months 个月，自动夹紧到月末（不依赖 dateutil）。"""
    idx = d.year * 12 + (d.month - 1) + months
    y, m0 = divmod(idx, 12)
    m = m0 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


@dataclass
class PlanRow:
    period: int
    due_date: date
    planned_principal: Decimal
    planned_interest: Decimal

    @property
    def planned_total(self) -> Decimal:
        return q2(self.planned_principal + self.planned_interest)


def generate_plan(
    *,
    principal: Decimal,
    annual_rate: Decimal,
    term_periods: int,
    payment_freq: str,
    method: str,
    disbursement_date: date,
) -> list[PlanRow]:
    if payment_freq not in FREQS_PER_YEAR:
        raise ValueError(f"未知 payment_freq: {payment_freq}")
    if method not in ("等额本息", "等额本金"):
        raise ValueError(f"未知 method: {method}")
    if term_periods <= 0:
        raise ValueError("term_periods 必须 > 0")

    ppy = FREQS_PER_YEAR[payment_freq]
    months_per_period = 12 // ppy
    i = annual_rate / ppy
    n = term_periods

    principals: list[Decimal] = []
    interests: list[Decimal] = []

    if method == "等额本息":
        if i == 0:
            installment = q2(principal / n)
        else:
            factor = (Decimal(1) + i) ** n
            installment = q2(principal * i * factor / (factor - 1))
        remaining = principal
        for _ in range(n):
            interest = q2(remaining * i)
            principal_k = q2(installment - interest)
            interests.append(interest)
            principals.append(principal_k)
            remaining -= principal_k
    else:  # 等额本金
        base = q2(principal / n)
        remaining = principal
        for _ in range(n):
            interest = q2(remaining * i)
            interests.append(interest)
            principals.append(base)
            remaining -= base

    # 末期吸收尾差，使 Σprincipal == principal（NW1）
    diff = q2(principal - sum(principals))
    principals[-1] = q2(principals[-1] + diff)

    return [
        PlanRow(
            period=k + 1,
            due_date=add_months(disbursement_date, (k + 1) * months_per_period),
            planned_principal=principals[k],
            planned_interest=interests[k],
        )
        for k in range(n)
    ]
