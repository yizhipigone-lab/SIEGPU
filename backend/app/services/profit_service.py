"""利润测算引擎（移植庭宇 1372 台测算表模型）。

月度现金流 = 租金收入 - 运营成本 - 金租还款（本+息）
期初 = -自有资金（押金/股权投入）
期末 = +残值 + 押金收回
IRR/NPV/回本期 基于完整现金流序列。
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Contract, Project
from app.utils.repayment_plan import generate_plan, FREQS_PER_YEAR


class ProfitInput(BaseModel):
    purchase_ex_tax: Decimal = Field(description="采购不含税")
    purchase_incl_tax: Decimal = Field(description="采购含税")
    monthly_rent: Decimal = Field(description="月租金(含税)")
    term_months: int = Field(gt=0, description="出租月数")
    annual_rate: Decimal = Field(ge=0, lt=1, description="金租年利率(小数)")
    lease_term: int = Field(gt=0, description="金租期数")
    payment_freq: Literal["月", "季", "半年"] = "月"
    repayment_method: Literal["等额本息", "等额本金"] = "等额本息"
    depreciation_years: int = 5
    residual_rate: Decimal = Decimal("0.10")
    monthly_opex: Decimal = Field(default=Decimal("0"), description="月运营成本")
    tax_rate: Decimal = Decimal("0.06")
    equity_ratio: Decimal = Field(default=Decimal("0.10"), description="自有比例(押金/股权)")


def _irr(cashflows: list[float], lo: float = -0.99, hi: float = 10.0, iters: int = 200) -> float | None:
    """二分法求 IRR（月利率）。"""
    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** i for i, cf in enumerate(cashflows))
    nlo, nhi = npv(lo), npv(hi)
    if nlo * nhi > 0:
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2
        v = npv(mid)
        if abs(v) < 0.01:
            return mid
        if v * nlo < 0:
            hi = mid
        else:
            lo, nlo = mid, v
    return mid


def calculate_model(p: ProfitInput) -> dict:
    """计算月度现金流 + IRR/NPV/回本期 + 汇总。"""
    # 金租还款计划
    plan = generate_plan(
        principal=p.purchase_incl_tax, annual_rate=p.annual_rate,
        term_periods=p.lease_term, payment_freq=p.payment_freq,
        method=p.repayment_method, disbursement_date=date(2026, 1, 1),
    )
    ppy = FREQS_PER_YEAR[p.payment_freq]
    mpp = 12 // ppy

    # 循环不变常量（每月的租金/成本/税率固定，提前算一次）
    purchase_ex = float(p.purchase_ex_tax)
    resid_rate = float(p.residual_rate)
    tax_rate = float(p.tax_rate)
    rent = float(p.monthly_rent)
    rent_ex = rent / (1 + tax_rate)
    opex = float(p.monthly_opex)
    term_months = p.term_months

    equity = float(p.purchase_incl_tax) * float(p.equity_ratio)
    initial_cf = -equity
    depreciable = purchase_ex * (1 - resid_rate)
    monthly_dep = depreciable / (p.depreciation_years * 12)

    rows: list[dict] = []
    cumulative = initial_cf
    payback: int | None = None
    total_rent_ex = 0.0
    total_opex = 0.0
    total_dep = 0.0
    total_lease_i = 0.0
    net_sum = 0.0

    for m in range(1, term_months + 1):
        # 金租还款（按期，非还款月为 0）
        idx = (m - 1) // mpp
        if m % mpp == 0 and idx < len(plan):
            lease_p = float(plan[idx].planned_principal)
            lease_i = float(plan[idx].planned_interest)
        else:
            lease_p = 0.0
            lease_i = 0.0

        pre_tax = rent_ex - opex - monthly_dep - lease_i
        net_cash = rent - opex - lease_p - lease_i

        # 期末回收
        if m == term_months:
            residual = purchase_ex * resid_rate
            net_cash += residual + equity

        cumulative += net_cash
        if cumulative >= 0 and payback is None:
            payback = m

        # 汇总在循环内累计（与行内已四舍五入的值一致）
        rent_r = round(rent, 2)
        opex_r = round(opex, 2)
        dep_r = round(monthly_dep, 2)
        lease_i_r = round(lease_i, 2)
        net_r = round(net_cash, 2)
        total_rent_ex += rent_r / (1 + tax_rate)
        total_opex += opex_r
        total_dep += dep_r
        total_lease_i += lease_i_r
        net_sum += net_r

        rows.append({
            "month": m, "rent": rent_r, "opex": opex_r,
            "depreciation": dep_r,
            "lease_principal": round(lease_p, 2), "lease_interest": lease_i_r,
            "pre_tax_profit": round(pre_tax, 2), "net_cashflow": net_r,
            "cumulative": round(cumulative, 2),
        })

    # IRR
    cfs = [initial_cf] + [r["net_cashflow"] for r in rows]
    m_irr = _irr(cfs)
    a_irr = round(m_irr * 12 * 100, 2) if m_irr is not None else None

    # NPV (年化 5%)
    nr = 0.05 / 12
    npv_val = round(sum(cf / (1 + nr) ** i for i, cf in enumerate(cfs)), 2)

    return {
        "monthly": rows,
        "summary": {
            "equity_investment": round(equity, 2),
            "total_revenue_ex_tax": round(total_rent_ex, 2),
            "total_opex": round(total_opex, 2),
            "total_depreciation": round(total_dep, 2),
            "total_lease_interest": round(total_lease_i, 2),
            "total_profit": round(total_rent_ex - total_opex - total_dep - total_lease_i, 2),
            "irr_annual_pct": a_irr,
            "npv_5pct": npv_val,
            "payback_month": payback,
            "monthly_net_avg": round(net_sum / len(rows), 2),
        },
    }


def calculate_for_project(db: Session, project_id: str) -> dict:
    """从项目已有数据自动提取参数并计算。"""
    proj = db.get(Project, project_id)
    if not proj:
        return {"error": "项目不存在"}
    # 从项目的合同中提取参数
    contracts = db.execute(select(Contract).where(Contract.project_id == project_id)).scalars().all()
    sales = [c for c in contracts if c.type == "SALES"]
    purchase = [c for c in contracts if c.type == "PURCHASE"]
    if not sales or not purchase:
        return {"error": "项目缺少销售或采购合同"}

    s = sales[0]
    pur = purchase[0]
    purchase_incl = float(pur.amount) * 1.13  # 不含税→含税估算
    inputs = ProfitInput(
        purchase_ex_tax=float(pur.amount),
        purchase_incl_tax=purchase_incl,
        monthly_rent=float(s.monthly_rent or 0),
        term_months=60,
        annual_rate=Decimal("0.04"),
        lease_term=60,
        payment_freq="月",
        repayment_method="等额本息",
        monthly_opex=Decimal("4116000"),  # 默认运营成本
    )
    return calculate_model(inputs)
