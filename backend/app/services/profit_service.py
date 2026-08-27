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
    """从项目已有数据自动提取参数并计算（v3.1：读 LeasingProcess + Contract 实际值）。"""
    from app.core.exceptions import BusinessError
    from app.models.leasing import LeasingProcess

    proj = db.get(Project, project_id)
    if not proj:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)

    contracts = db.execute(select(Contract).where(Contract.project_id == project_id)).scalars().all()
    sales = [c for c in contracts if c.type == "SALES"]
    purchase = [c for c in contracts if c.type == "PURCHASE"]
    if not sales or not purchase:
        raise BusinessError("BAD_REQUEST", "项目缺少销售或采购合同", 400)

    s = sales[0]
    pur = purchase[0]

    # v3.1：读 LeasingProcess 实际融资参数
    lp = db.execute(
        select(LeasingProcess).where(
            LeasingProcess.project_id == project_id,
            LeasingProcess.status == "已放款",
        ).order_by(LeasingProcess.disbursement_date.desc())
    ).scalars().first()

    purchase_ex = float(pur.amount)
    purchase_incl = purchase_ex * float(1 + pur.tax_rate)
    tax_rate = float(s.tax_rate) if s.tax_rate else 0.13  # 合同税率，默认13%

    if lp:
        annual_rate = lp.annual_rate if lp.annual_rate is not None else Decimal("0.04")
        lease_term = lp.term_periods or 60
        payment_freq = lp.payment_freq or "月"
        repayment_method = lp.repayment_method or "等额本息"
    else:
        annual_rate = Decimal("0.04")
        lease_term = 60
        payment_freq = "月"
        repayment_method = "等额本息"

    inputs = ProfitInput(
        purchase_ex_tax=Decimal(str(purchase_ex)),
        purchase_incl_tax=Decimal(str(purchase_incl)),
        monthly_rent=s.monthly_rent or Decimal("0"),
        term_months=lease_term,
        annual_rate=Decimal(str(annual_rate)),
        lease_term=lease_term,
        payment_freq=payment_freq,
        repayment_method=repayment_method,
        monthly_opex=Decimal("0"),  # 从实际支出汇总或外部参数
        tax_rate=Decimal(str(tax_rate)),
        equity_ratio=Decimal("0.10"),
    )
    result = calculate_model(inputs)
    # 挂项目名便于前端展示
    result["project_name"] = proj.name
    result["project_code"] = proj.code
    return result


def save_scenario(db: Session, *, project_id, name, params_json, result_json,
                  is_actual=False, created_by=None):
    """保存盈利测算场景。"""
    from app.models.profit_scenario import ProfitScenario
    from datetime import datetime
    scenario = ProfitScenario(
        project_id=project_id, name=name,
        params_json=params_json, result_json=result_json,
        is_actual=is_actual, calculated_at=datetime.utcnow(),
        created_by=created_by,
    )
    db.add(scenario)
    db.flush()
    return scenario


def list_scenarios(db: Session, *, project_id, skip=0, limit=50):
    from app.models.profit_scenario import ProfitScenario
    stmt = select(ProfitScenario).where(
        ProfitScenario.project_id == project_id,
        ProfitScenario.deleted_at.is_(None),
    ).order_by(ProfitScenario.created_at.desc()).offset(skip).limit(limit)
    return db.execute(stmt).scalars().all()


def compare_scenarios(db: Session, *, project_id) -> dict:
    """测算 vs 实际对比：取最新的 is_actual=False 场景和 is_actual=True 场景。"""
    from app.models.profit_scenario import ProfitScenario

    _q = lambda is_actual: db.execute(
        select(ProfitScenario).where(
            ProfitScenario.project_id == project_id,
            ProfitScenario.is_actual == is_actual,
            ProfitScenario.deleted_at.is_(None),
        ).order_by(ProfitScenario.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    estimated = _q(False)
    actual = _q(True)
    if not estimated or not actual:
        return {"estimated": None, "actual": None, "diffs": []}
    est_summary = estimated.result_json.get("summary", {})
    act_summary = actual.result_json.get("summary", {})
    diffs = []
    for key in ["total_revenue_ex_tax", "total_opex", "total_depreciation",
                "total_lease_interest", "total_profit", "irr_annual_pct", "npv_5pct"]:
        ev = est_summary.get(key)
        av = act_summary.get(key)
        if ev is not None and av is not None and ev != av:
            try:
                delta = round(float(av) - float(ev), 2)
            except (TypeError, ValueError):
                delta = None
            diffs.append({"key": key, "estimated": ev, "actual": av, "delta": delta})
    return {"estimated": estimated.result_json, "actual": actual.result_json, "diffs": diffs}
