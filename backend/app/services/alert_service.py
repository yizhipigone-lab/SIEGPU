"""应用内告警（§5.8）。计算当前触发的预警，不接邮件/企微（二期）。"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import Invoice
from app.models.capital import CapitalAllocation, CapitalTransaction
from app.models.leasing import LeasingNode, LeasingProcess
from app.models.repayment import Repayment

from . import capital_service


def _payable_30d(db: Session, today: date) -> Decimal:
    horizon = today + timedelta(days=30)
    r1 = db.execute(
        select(func.coalesce(func.sum(Repayment.planned_principal + Repayment.planned_interest), 0))
        .where(Repayment.due_date <= horizon, Repayment.status == "待还")
    ).scalar() or Decimal(0)
    r2 = db.execute(
        select(func.coalesce(func.sum(Invoice.amount), 0))
        .where(Invoice.direction == "PAYABLE", Invoice.due_date <= horizon,
               Invoice.status.notin_(["已付款", "已红冲"]))
    ).scalar() or Decimal(0)
    return Decimal(r1) + Decimal(r2)


def compute_alerts(db: Session) -> list[dict]:
    today = date.today()
    alerts: list[dict] = []

    # 1. 还款逾期
    for r in db.execute(
        select(Repayment).where(Repayment.due_date < today, Repayment.status == "待还")
    ).scalars():
        alerts.append({"level": "高危", "code": "REPAYMENT_OVERDUE",
                       "message": f"第 {r.period} 期还款逾期（到期 {r.due_date}）", "ref_id": str(r.id)})

    # 2. 调配逾期未归还
    for a in db.execute(
        select(CapitalAllocation).where(
            CapitalAllocation.expected_return_date < today, CapitalAllocation.status == "已调配")
    ).scalars():
        alerts.append({"level": "警告", "code": "ALLOCATION_OVERDUE",
                       "message": f"调配 {a.amount} 逾期未归还（应还 {a.expected_return_date}）", "ref_id": str(a.id)})

    # 3. 金租实际放款 ≠ 申请额
    for lp in db.execute(
        select(LeasingProcess).where(LeasingProcess.status == "已放款",
                                     LeasingProcess.actual_disbursement_amount.is_not(None))
    ).scalars():
        diff = abs(lp.actual_disbursement_amount - lp.total_amount)
        if diff > lp.total_amount * Decimal("0.01"):
            alerts.append({"level": "警告", "code": "DISBURSE_MISMATCH",
                           "message": f"金租实际放款 {lp.actual_disbursement_amount} 与申请 {lp.total_amount} 不符",
                           "ref_id": str(lp.id)})

    # 4. 金租放款延迟（放款节点计划日已过未完成）
    for n in db.execute(
        select(LeasingNode).where(LeasingNode.node_name == "放款",
                                  LeasingNode.planned_date.is_not(None), LeasingNode.planned_date < today,
                                  LeasingNode.status != "已完成")
    ).scalars():
        alerts.append({"level": "高危", "code": "DISBURSE_DELAY",
                       "message": f"金租放款延迟（计划日 {n.planned_date}）", "ref_id": str(n.process_id)})

    # 5. 资金池余额 < 未来30天应付
    inn, out = capital_service._dir_sums(db)
    balance = inn - out
    payable = _payable_30d(db, today)
    if payable > 0 and balance < payable:
        alerts.append({"level": "高危", "code": "POOL_INSUFFICIENT",
                       "message": f"资金池余额 {balance} < 未来30天应付 {payable}"})

    # 6. 交付阶段卡住（>7天未推进）
    from app.models.delivery import DeliveryStage
    cutoff = today - timedelta(days=7)
    for ds in db.execute(
        select(DeliveryStage).where(
            DeliveryStage.status == "进行中", DeliveryStage.updated_at < cutoff)
    ).scalars():
        alerts.append({"level": "警告", "code": "DELIVERY_STUCK",
                       "message": f"交付阶段「{ds.stage}」停滞超过 7 天", "ref_id": str(ds.order_id)})

    # 7. 合同到期（<30天）
    from app.models.project import Contract
    horizon = today + timedelta(days=30)
    for ct in db.execute(
        select(Contract).where(Contract.end_date.is_not(None), Contract.end_date <= horizon,
                               Contract.end_date >= today, Contract.status == "执行中")
    ).scalars():
        days_left = (ct.end_date - today).days
        alerts.append({"level": "提示", "code": "CONTRACT_EXPIRING",
                       "message": f"合同 {ct.contract_no} 将于 {days_left} 天后到期", "ref_id": str(ct.id)})

    # 8. 工作流停滞（>14天未动）
    from app.models.project_workflow import ProjectWorkflow
    from app.models.project import Project as Pj
    cutoff14 = today - timedelta(days=14)
    for w in db.execute(
        select(ProjectWorkflow).where(
            ProjectWorkflow.status == "进行中", ProjectWorkflow.updated_at < cutoff14)
    ).scalars():
        proj = db.get(Pj, w.project_id)
        pname = proj.name if proj else str(w.project_id)
        alerts.append({"level": "警告", "code": "WORKFLOW_STUCK",
                       "message": f"项目「{pname}」工作流停滞超过 14 天", "ref_id": str(w.project_id)})

    return alerts
