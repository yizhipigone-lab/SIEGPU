"""经营看板服务（三期 §4.5 Dashboard 升级）。

四块：核心指标 / 待办中心 / 资金预测概览（简易版，未接 §4.6 引擎）/ EBS 同步状态。
口径：金额默认不含税（与客户对账自洽）；融资余额=金租已放款总额（actual 优先）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import Invoice
from app.models.capital import CapitalTransaction
from app.models.device import Device
from app.models.ebs import EbsSyncLog
from app.models.insurance import InsurancePolicy
from app.models.leasing import LeasingProcess
from app.models.payment import Approval
from app.models.project import Contract
from app.models.repayment import Repayment
from app.models.revenue import RevenueRecognition
from app.utils.reconcile import q2


def _sum(db, col, *conds) -> Decimal:
    return Decimal(db.execute(select(func.coalesce(func.sum(col), 0)).where(*conds)).scalar() or 0)


def _metrics(db: Session) -> dict:
    today = date.today()
    month_start = today.replace(day=1)
    contract_current = _sum(db, Contract.amount,
                            Contract.created_at >= month_start, Contract.deleted_at.is_(None))
    received = _sum(db, Invoice.amount_ex_tax, Invoice.direction == "RECEIVABLE",
                    Invoice.paid_date.isnot(None), Invoice.status != "已红冲")
    invoiced = _sum(db, Invoice.amount_ex_tax, Invoice.status != "已红冲",
                    Invoice.deleted_at.is_(None))
    recognized = _sum(db, RevenueRecognition.amount,
                      RevenueRecognition.status.in_(("已确认", "已同步EBS")))
    disbursed = _sum(db, func.coalesce(LeasingProcess.actual_disbursement_amount, LeasingProcess.total_amount),
                     LeasingProcess.status == "已放款", LeasingProcess.deleted_at.is_(None))
    repaid = _sum(db, Repayment.planned_principal, Repayment.status == "已还")
    inn = _sum(db, CapitalTransaction.amount, CapitalTransaction.direction == "IN",
               CapitalTransaction.deleted_at.is_(None))
    out = _sum(db, CapitalTransaction.amount, CapitalTransaction.direction == "OUT",
               CapitalTransaction.deleted_at.is_(None))
    # 监管账户余额：监管户合同 回款−项目还款
    supervised = Decimal(0)
    for c in db.execute(select(Contract).where(
            Contract.type == "SALES", Contract.collection_account_type == "监管户")).scalars().all():
        rec = _sum(db, Invoice.amount, Invoice.contract_id == c.id,
                   Invoice.paid_date.isnot(None), Invoice.status != "已红冲")
        rep = _sum(db, CapitalTransaction.amount,
                   CapitalTransaction.project_id == c.project_id,
                   CapitalTransaction.source_type == "还款", CapitalTransaction.deleted_at.is_(None))
        supervised += rec - rep
    total_dev = db.execute(select(func.count(Device.id)).where(
        Device.deleted_at.is_(None))).scalar() or 0
    lit_dev = db.execute(select(func.count(Device.id)).where(
        Device.deleted_at.is_(None), Device.status == "点亮验收")).scalar() or 0
    return {
        "contract_amount_current": q2(contract_current),   # 当期（本月新签）合同额
        "total_received": q2(received),
        "invoiced_total": q2(invoiced),
        "recognized_total": q2(recognized),
        "leasing_balance": q2(disbursed - repaid),          # 融资余额 = 已放款 − 已还本金
        "pool_balance": q2(inn - out),
        "supervised_balance": q2(supervised),
        "device_lit": int(lit_dev),
        "device_total": int(total_dev),
    }


def _todo_center(db: Session) -> list[dict]:
    """待办中心（计数型）：付款审批 / 待投保确认 / 预付款未结清 / 待还款(30天) / 监管预警 / 资金缺口。"""
    today = date.today()
    items = []
    n = db.execute(select(func.count(Approval.id)).where(
        Approval.status == "待审批", Approval.deleted_at.is_(None))).scalar() or 0
    items.append({"kind": "付款/收入审批", "count": int(n), "route": "/payments",
                  "level": "警告" if n else "正常"})
    n = db.execute(select(func.count(InsurancePolicy.id)).where(
        InsurancePolicy.status == "待确认", InsurancePolicy.deleted_at.is_(None))).scalar() or 0
    items.append({"kind": "待投保确认", "count": int(n), "route": "/insurance",
                  "level": "警告" if n else "正常"})
    n = db.execute(select(func.count(Device.id)).where(
        Device.prepayment_amount > 0, Device.prepayment_settled.is_(False),
        Device.deleted_at.is_(None))).scalar() or 0
    items.append({"kind": "预付款未结清设备", "count": int(n), "route": "/prepayments",
                  "level": "正常"})
    from datetime import timedelta
    horizon = today + timedelta(days=30)
    n = db.execute(select(func.count(Repayment.id)).where(
        Repayment.status == "待还", Repayment.due_date <= horizon,
        Repayment.deleted_at.is_(None))).scalar() or 0
    items.append({"kind": "待还款（30天内）", "count": int(n), "route": "/leasing",
                  "level": "警告" if n else "正常"})
    # 监管账户预警（复用对账中心 dim4 口径）
    from app.services import reconciliation_service as _rc
    n = sum(1 for r in _rc.dim4_supervised_accounts(db) if r["flags"])
    items.append({"kind": "监管账户预警", "count": n, "route": "/reconciliation-center",
                  "level": "高危" if n else "正常"})
    # 资金缺口（复用 alert_service 口径：余额 < 未来30天应付）
    from app.services import alert_service as _al
    gap = any(a["code"] == "POOL_INSUFFICIENT" for a in _al.compute_alerts(db))
    items.append({"kind": "资金缺口预警", "count": 1 if gap else 0, "route": "/capital",
                  "level": "高危" if gap else "正常"})
    return items


def _forecast(db: Session) -> list[dict]:
    """资金预测概览（简易版，未接 §4.6 引擎）：未来 3 个月
    流入=销售合同月租（含税），流出=当月到期还款+未付采购发票；期末=滚动余额。"""
    from app.models.device import Device as _D
    inn = _sum(db, CapitalTransaction.amount, CapitalTransaction.direction == "IN",
               CapitalTransaction.deleted_at.is_(None))
    out = _sum(db, CapitalTransaction.amount, CapitalTransaction.direction == "OUT",
               CapitalTransaction.deleted_at.is_(None))
    balance = inn - out
    monthly_rent = _sum(db, Contract.monthly_rent,
                        Contract.type == "SALES", Contract.status.in_(("已签", "执行中")),
                        Contract.monthly_rent.isnot(None))
    rows = []
    today = date.today()
    for i in range(1, 4):
        y, m = today.year, today.month + i
        if m > 12:
            y, m = y + 1, m - 12
        month_start = date(y, m, 1)
        month_end = date(y + (m == 12), (m % 12) + 1, 1)
        repays = _sum(db, Repayment.planned_principal + Repayment.planned_interest,
                      Repayment.status == "待还",
                      Repayment.due_date >= month_start, Repayment.due_date < month_end)
        payables = _sum(db, Invoice.amount, Invoice.direction == "PAYABLE",
                        Invoice.paid_date.is_(None), Invoice.status != "已红冲",
                        Invoice.due_date >= month_start, Invoice.due_date < month_end)
        inflow = monthly_rent
        outflow = repays + payables
        closing = balance + inflow - outflow
        rows.append({"month": f"{y}-{m:02d}", "opening": q2(balance), "inflow": q2(inflow),
                     "outflow": q2(outflow), "closing": q2(closing),
                     "gap": closing < 0})
        balance = closing
    return rows


def _ebs_stats(db: Session) -> dict:
    rows = db.execute(select(EbsSyncLog.status, func.count(EbsSyncLog.id)).group_by(
        EbsSyncLog.status)).all()
    by = {s: int(n) for s, n in rows}
    last = db.execute(select(func.max(EbsSyncLog.synced_at))).scalar()
    return {"success": by.get("MOCK_SUCCESS", 0) + by.get("SUCCESS", 0),
            "failed": by.get("FAILED", 0),
            "last_synced_at": last.isoformat() if last else None}


def business_board(db: Session) -> dict:
    return {
        "metrics": _metrics(db),
        "todo_center": _todo_center(db),
        "forecast": _forecast(db),
        "ebs": _ebs_stats(db),
    }
