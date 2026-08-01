"""还款服务：列表 + 逐期确认（实际还本付息）。"""
from sqlalchemy import select
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
