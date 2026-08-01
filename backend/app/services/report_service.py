"""报表（聚合查询版；利润测算沿用设计留二期）。"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.billing import Billing
from app.models.capital import CapitalTransaction
from app.models.leasing import LeasingProcess
from app.models.project import Project

from . import capital_service


def capital_monthly(db: Session) -> list[dict]:
    """按月汇总资金流（入/出/净）。"""
    month_expr = func.to_char(CapitalTransaction.transaction_date, "YYYY-MM")
    rows = db.execute(
        select(month_expr, CapitalTransaction.direction, func.coalesce(func.sum(CapitalTransaction.amount), 0))
        .group_by(month_expr, CapitalTransaction.direction)
        .order_by(month_expr)
    ).all()
    months: dict[str, dict] = {}
    for m, d, s in rows:
        b = months.setdefault(m, {"month": m, "in": Decimal(0), "out": Decimal(0)})
        if d == "IN":
            b["in"] += Decimal(s)
        else:
            b["out"] += Decimal(s)
    for b in months.values():
        b["net"] = b["in"] - b["out"]
    return list(months.values())


def project_overview(db: Session) -> list[dict]:
    out = []
    for p in db.execute(select(Project)).scalars():
        np = capital_service.project_net_position(db, p.id)
        lps = db.execute(select(LeasingProcess).where(LeasingProcess.project_id == p.id)).scalars().all()
        assets = db.execute(select(Asset).where(Asset.project_id == p.id)).scalars().all()
        dep = sum((a.monthly_depreciation for a in assets), Decimal(0))
        out.append({
            "project_id": str(p.id), "name": p.name,
            "total_investment": p.total_investment, "net_position": np,
            "leasing_count": len(lps), "leasing_status": lps[0].status if lps else None,
            "asset_count": len(assets), "monthly_depreciation": dep,
        })
    return out


def receivables_aging(db: Session) -> dict:
    """未回款 billings 按账龄分桶。"""
    today = date.today()
    buckets = {"0-30": Decimal(0), "31-60": Decimal(0), "60+": Decimal(0)}
    for b in db.execute(select(Billing).where(Billing.status != "已收款")).scalars():
        days = (today - b.billing_date).days
        if days <= 30:
            buckets["0-30"] += b.amount
        elif days <= 60:
            buckets["31-60"] += b.amount
        else:
            buckets["60+"] += b.amount
    return buckets
