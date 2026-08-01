"""计费服务（§5.3）：为已点亮订单的销售合同按期生成 billings。复用 utils/billing。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.billing import Billing
from app.models.delivery import DeliveryStage
from app.models.project import Contract
from app.models.delivery import Order
from app.utils.billing import billing_amount, days_in_month, split_tax


def _light_on_date(db: Session, order_id):
    st = db.execute(
        select(DeliveryStage).where(DeliveryStage.order_id == order_id, DeliveryStage.stage == "点亮")
    ).scalar_one_or_none()
    if not st or st.status != "已完成" or st.actual_date is None:
        raise BusinessError("BAD_REQUEST", "订单尚未点亮，无法计费（计费起点=点亮日）", 400)
    return st.actual_date


def generate_billing(db: Session, *, order_id, contract_id, period_index: int, billing_date,
                     created_by, idempotency_key: str | None = None) -> Billing:
    o = db.get(Order, order_id)
    if not o or o.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "订单不存在", 404)
    c = db.get(Contract, contract_id)
    if not c or c.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "合同不存在", 404)
    if c.type != "SALES" or not c.monthly_rent:
        raise BusinessError("BAD_REQUEST", "计费需销售合同且已设 monthly_rent", 400)

    light = _light_on_date(db, order_id)
    amount = billing_amount(c.monthly_rent, period_index, light)  # 含税
    ex, tax = split_tax(amount, c.tax_rate)
    if period_index == 1:
        days = days_in_month(light) - light.day + 1  # 含点亮当日
    else:
        days = days_in_month(billing_date)

    # v3.1: duplicated period check (unique index now on sales_order_id+period_index)
    existing = db.execute(
        select(Billing).where(
            Billing.order_id == order_id, Billing.period_index == period_index,
            Billing.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing:
        raise BusinessError("DUPLICATE", f"订单 {order_id} 第 {period_index} 期已计费", 409)

    b = Billing(
        project_id=o.project_id, contract_id=contract_id, order_id=order_id,
        period_index=period_index, period_label=f"{billing_date.year}-{billing_date.month:02d}",
        billing_date=billing_date, days_in_period=days, amount=amount, amount_ex_tax=ex,
        tax_amount=tax, tax_rate=c.tax_rate, idempotency_key=idempotency_key,
    )
    db.add(b)
    db.flush()
    from app.services import workflow_service as _wf
    _wf.after_action(db, o.project_id)
    return b


def list_billings(db: Session, contract_id=None, order_id=None):
    stmt = select(Billing).order_by(Billing.billing_date.desc())
    if contract_id:
        stmt = stmt.where(Billing.contract_id == contract_id)
    if order_id:
        stmt = stmt.where(Billing.order_id == order_id)
    return db.execute(stmt).scalars().all()
