"""报表（聚合查询版；利润测算沿用设计留二期）。"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.billing import Billing, Invoice
from app.models.capital import CapitalTransaction
from app.models.leasing import LeasingProcess
from app.models.project import Contract, Project

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


def project_comparison(db: Session) -> list[dict]:
    """项目对比：IRR/NPV/回款率/逾期笔数/工作流进度。"""
    from app.models.repayment import Repayment
    from app.models.profit_scenario import ProfitScenario
    from app.models.project_workflow import ProjectWorkflow

    rows = []
    for p in db.execute(select(Project)).scalars():
        # 盈利指标
        ps = db.execute(
            select(ProfitScenario).where(
                ProfitScenario.project_id == p.id, ProfitScenario.is_actual == True,
                ProfitScenario.deleted_at.is_(None),
            ).order_by(ProfitScenario.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        summary = ps.result_json.get("summary", {}) if ps else {}

        # 回款率：已收款 / 已开票
        billed = db.execute(
            select(func.coalesce(func.sum(Billing.amount), 0)).where(
                Billing.project_id == p.id, Billing.status != "已红冲")
        ).scalar() or Decimal(0)
        received = db.execute(
            select(func.coalesce(func.sum(Invoice.amount), 0)).where(
                Invoice.contract_id.in_(
                    select(Contract.id).where(Contract.project_id == p.id)
                ), Invoice.direction == "RECEIVABLE",
                Invoice.paid_date.isnot(None), Invoice.status != "已红冲")
        ).scalar() or Decimal(0)
        collection_rate = float(received) / float(billed) if billed > 0 else None

        # 逾期：与预警 REPAYMENT_OVERDUE 同口径（待还 + due_date < 今天）
        from datetime import date as _d
        overdue_repay = db.execute(
            select(func.count()).where(
                Repayment.leasing_process_id.in_(
                    select(LeasingProcess.id).where(LeasingProcess.project_id == p.id)
                ), Repayment.status == "待还", Repayment.due_date < _d.today()
            )
        ).scalar() or 0

        # 工作流进度
        wf = db.execute(
            select(ProjectWorkflow).where(ProjectWorkflow.project_id == p.id)
        ).scalar_one_or_none()
        progress = round(
            sum(1 for s in wf.steps if s.get("status") in ("done", "skip")) / len(wf.steps) * 100
        ) if wf and wf.steps else 0

        rows.append({
            "project_id": str(p.id), "project_name": p.name,
            "irr": summary.get("irr_annual_pct"), "npv": summary.get("npv_5pct"),
            "total_profit": summary.get("total_profit"),
            "collection_rate": round(collection_rate * 100, 1) if collection_rate is not None else None,
            "overdue_count": overdue_repay,
            "progress_pct": progress,
        })
    return rows
