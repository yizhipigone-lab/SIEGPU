"""发票对账与超开校验（纯函数）。对应设计书 §5.6：三流勾稽 + 超开拦截。"""
from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")
DEFAULT_TOLERANCE = Decimal("0.001")  # 0.1%


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def reconcile_contract(
    *,
    contract_amount_ex_tax: Decimal,
    billed_ex_tax: Decimal,
    invoiced_ex_tax: Decimal,
    received_amount: Decimal,
) -> dict:
    """收端三流勾稽：合同 → 应收(计费) → 已开票 → 已收款，逐级差异。"""
    return {
        "contract": q2(contract_amount_ex_tax),
        "billed": q2(billed_ex_tax),
        "invoiced": q2(invoiced_ex_tax),
        "received": q2(received_amount),
        "gap_contract_vs_billed": q2(contract_amount_ex_tax - billed_ex_tax),
        "gap_billed_vs_invoiced": q2(billed_ex_tax - invoiced_ex_tax),
        "gap_invoiced_vs_received": q2(invoiced_ex_tax - received_amount),
    }


def is_over_contract(
    *,
    existing_ex_tax_sum: Decimal,
    new_ex_tax: Decimal,
    contract_amount_ex_tax: Decimal,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> bool:
    """超开判定：Σ已有 + 新增 > 合同额 × (1 + tolerance)。"""
    total = q2(existing_ex_tax_sum + new_ex_tax)
    cap = q2(contract_amount_ex_tax * (Decimal(1) + tolerance))
    return total > cap
