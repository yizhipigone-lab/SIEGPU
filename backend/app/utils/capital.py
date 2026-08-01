"""资金池算法（纯函数）。对应设计书 §5.1/§5.2（复审 NF5 修正版）。

可调余额 = 净头寸的正部。调配一旦发起，OUT 现金同事务写走，net_position 已隐含未归还调出额，
故不再额外减 frozen_out（否则重复扣减）。
"""
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def net_position(ins: list[Decimal], outs: list[Decimal]) -> Decimal:
    """项目净头寸 = Σ入金 − Σ出金。"""
    return q2(sum(ins) - sum(outs))


def allocatable(ins: list[Decimal], outs: list[Decimal]) -> Decimal:
    """可调余额 = max(0, 净头寸)。"""
    np = net_position(ins, outs)
    return np if np > 0 else Decimal(0)


def pool_balance(ins: list[Decimal], outs: list[Decimal]) -> Decimal:
    """资金池总余额 = ΣIN − ΣOUT（红冲反向记录方向相反、金额相等，参与求和自动抵消）。"""
    return net_position(ins, outs)
