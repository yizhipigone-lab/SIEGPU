"""报表（聚合查询版；利润测算沿用设计留二期）。"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.billing import Billing, Invoice
from app.models.capital import CapitalTransaction
from app.models.leasing import LeasingProcess
from app.models.master import Customer
from app.models.project import Contract, Project
from app.utils.reconcile import q2

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
        # W5-6：未激活资产卡 monthly_depreciation=None，求和须跳过（否则 TypeError）
        dep = sum((a.monthly_depreciation for a in assets if a.monthly_depreciation is not None), Decimal(0))
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


# —— v3.2 客户对账单（F3）——
# 口径与 invoice_service.reconciliation 完全一致（billed/invoiced/received 三流），
# 刻意绕开 receivables_aging（其依赖从未写入的「已收款」状态，是隐性 bug）。
# 维度从「合同」改为「客户」：取该客户所有 SALES 合同聚合。

def _customer_contract_totals(db: Session, contract_ids: list) -> dict:
    """对一组合同 id 聚合计费/开票/回款三流金额。
    全部用不含税口径（amount_ex_tax），让 gap 可直接相减——客户对账单要内部自洽。
    （与 invoice_service.reconciliation 的 billed/invoiced 同口径；received 改用 ex_tax 以保持一致。）
    """
    if not contract_ids:
        return {"billed": Decimal(0), "invoiced": Decimal(0), "received": Decimal(0)}
    billed = db.execute(
        select(func.coalesce(func.sum(Billing.amount_ex_tax), 0)).where(
            Billing.contract_id.in_(contract_ids), Billing.status != "已红冲")
    ).scalar() or Decimal(0)
    invoiced = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_ex_tax), 0)).where(
            Invoice.contract_id.in_(contract_ids), Invoice.direction == "RECEIVABLE",
            Invoice.status != "已红冲")
    ).scalar() or Decimal(0)
    received = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_ex_tax), 0)).where(
            Invoice.contract_id.in_(contract_ids), Invoice.direction == "RECEIVABLE",
            Invoice.paid_date.isnot(None), Invoice.status != "已红冲")
    ).scalar() or Decimal(0)
    return {"billed": billed, "invoiced": invoiced, "received": received}


def customer_statement(db: Session, customer_id) -> dict:
    """单个客户对账单：四 KPI（合同额/已计费/已开票/已回款）+ 每合同明细 + 流水明细。"""
    customer = db.get(Customer, customer_id)
    if not customer or customer.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "客户不存在", 404)

    contracts = db.execute(
        select(Contract).where(
            Contract.type == "SALES", Contract.party_type == "customer",
            Contract.party_id == customer_id)
    ).scalars().all()
    cids = [c.id for c in contracts]
    totals = _customer_contract_totals(db, cids)
    contract_amount = sum((c.amount for c in contracts), Decimal(0))

    # 每合同明细
    contract_items = []
    for c in contracts:
        ct = _customer_contract_totals(db, [c.id])
        contract_items.append({
            "contract_id": str(c.id), "contract_no": c.contract_no or "—",
            "contract_amount": q2(c.amount),
            "billed": q2(ct["billed"]), "invoiced": q2(ct["invoiced"]),
            "received": q2(ct["received"]),
            "gap": q2(c.amount - ct["billed"]),
            "status": c.status,
        })

    # 流水明细：该客户合同下的计费单 + 发票，按日期倒序合并
    line_items = []
    for b in db.execute(
        select(Billing).where(Billing.contract_id.in_(cids)).order_by(Billing.billing_date.desc())
    ).scalars().all():
        line_items.append({
            "date": b.billing_date.isoformat() if b.billing_date else None,
            "contract_no": _contract_no(contracts, b.contract_id),
            "type": "计费", "amount_ex_tax": q2(b.amount_ex_tax),
            "status": b.status,
        })
    for inv in db.execute(
        select(Invoice).where(Invoice.contract_id.in_(cids), Invoice.direction == "RECEIVABLE")
        .order_by(Invoice.issue_date.desc())
    ).scalars().all():
        line_items.append({
            "date": (inv.paid_date or inv.issue_date).isoformat() if (inv.paid_date or inv.issue_date) else None,
            "contract_no": _contract_no(contracts, inv.contract_id),
            "type": "回款" if inv.paid_date else "开票",
            "amount_ex_tax": q2(inv.amount_ex_tax),
            "status": inv.status,
        })
    line_items.sort(key=lambda r: r["date"] or "", reverse=True)

    return {
        "customer_id": str(customer_id), "customer_name": customer.name,
        "contract_amount": q2(contract_amount),
        "billed": q2(totals["billed"]), "invoiced": q2(totals["invoiced"]),
        "received": q2(totals["received"]),
        "gap_unbilled": q2(contract_amount - totals["billed"]),
        "gap_uncollected": q2(totals["invoiced"] - totals["received"]),
        "contracts": contract_items,
        "line_items": line_items,
    }


def customer_statement_summary(db: Session) -> list[dict]:
    """客户对账总览：每个有销售合同的客户一行（用于下拉/列表挑选）。"""
    # 有销售合同的全部客户 id（去重）
    cust_ids = db.execute(
        select(Contract.party_id).where(
            Contract.type == "SALES", Contract.party_type == "customer")
        .distinct()
    ).scalars().all()
    out = []
    for cid in cust_ids:
        cust = db.get(Customer, cid)
        if not cust or cust.deleted_at is not None:
            continue
        contracts = db.execute(
            select(Contract).where(
                Contract.type == "SALES", Contract.party_type == "customer",
                Contract.party_id == cid)
        ).scalars().all()
        cids = [c.id for c in contracts]
        totals = _customer_contract_totals(db, cids)
        contract_amount = sum((c.amount for c in contracts), Decimal(0))
        out.append({
            "customer_id": str(cid), "customer_name": cust.name,
            "contract_amount": q2(contract_amount),
            "billed": q2(totals["billed"]), "invoiced": q2(totals["invoiced"]),
            "received": q2(totals["received"]),
            "gap_uncollected": q2(totals["invoiced"] - totals["received"]),
            "contract_count": len(contracts),
        })
    out.sort(key=lambda r: r["gap_uncollected"], reverse=True)
    return out


def _contract_no(contracts: list, contract_id) -> str:
    for c in contracts:
        if c.id == contract_id:
            return c.contract_no or "—"
    return "—"
