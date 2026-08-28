"""还款服务：列表 + 逐期确认（实际还本付息）+ 计划调整（缺陷#11）。"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.repayment import Repayment


def list_repayments(db: Session, leasing_process_id):
    return db.execute(
        select(Repayment).where(Repayment.leasing_process_id == leasing_process_id).order_by(Repayment.period)
    ).scalars().all()


def confirm_repayment(db: Session, *, repayment_id, actual_principal, actual_interest, paid_date) -> Repayment:
    r = db.get(Repayment, repayment_id)
    if not r or r.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "还款记录不存在", 404)
    if r.status == "已还":
        raise BusinessError("DUPLICATE", "该期已确认还款", 409)
    r.actual_principal = actual_principal
    r.actual_interest = actual_interest
    r.paid_date = paid_date
    r.status = "已还"
    db.flush()
    return r


def _process_total_disbursed(db: Session, process_id) -> Decimal:
    """放款总额 = 主放款 actual_disbursement_amount + Σ分次放款（缺陷#11 上限基准，K8）。"""
    from app.models.leasing import LeasingDisbursement, LeasingProcess
    proc = db.get(LeasingProcess, process_id)
    total = Decimal(proc.actual_disbursement_amount or 0) if proc else Decimal(0)
    sub = db.execute(
        select(func.coalesce(func.sum(LeasingDisbursement.amount), 0)).where(
            LeasingDisbursement.process_id == process_id,
            LeasingDisbursement.deleted_at.is_(None),
        )
    ).scalar() or Decimal(0)
    return total + Decimal(sub)


def adjust_plan(db: Session, *, repayment_id, planned_principal=None, planned_interest=None,
                due_date=None) -> Repayment:
    """缺陷#11：还款计划按资金支付计划表调整（planned_* 可改）。

    - 已确认还款的期次禁改（防改历史）
    - Σ计划本金 ≤ 放款总额（含多笔放款），超则提示重新分配
    """
    r = db.get(Repayment, repayment_id)
    if not r or r.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "还款记录不存在", 404)
    if r.status == "已还":
        raise BusinessError("STATE_ERROR", "该期已确认还款，不可再改计划（请先红冲实际值或联系管理员）", 409)
    new_pp = r.planned_principal if planned_principal is None else planned_principal
    new_pi = r.planned_interest if planned_interest is None else planned_interest
    new_due = r.due_date if due_date is None else due_date
    if new_pp < 0 or new_pi < 0:
        raise BusinessError("VALIDATION_ERROR", "计划本金/利息不能为负", 422)
    others = db.execute(
        select(func.coalesce(func.sum(Repayment.planned_principal), 0)).where(
            Repayment.leasing_process_id == r.leasing_process_id,
            Repayment.id != r.id,
            Repayment.deleted_at.is_(None),
        )
    ).scalar() or Decimal(0)
    cap = _process_total_disbursed(db, r.leasing_process_id)
    if new_pp + Decimal(others) > cap:
        raise BusinessError(
            "VALIDATION_ERROR",
            f"调整后Σ计划本金 {new_pp + Decimal(others):,.2f} 超放款总额 {cap:,.2f}，请按资金支付计划重新分配",
            422,
        )
    r.planned_principal = new_pp
    r.planned_interest = new_pi
    r.due_date = new_due
    db.flush()
    return r
