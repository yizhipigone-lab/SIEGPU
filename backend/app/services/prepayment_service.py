"""预付款按月结转服务（二期 W9-10，D2 裁定）。

D2 裁定：不建 prepayments 表，devices 字段是预付款单一真源——
- `prepayment_amount`：预付款总额（一期已有，采购预付款分摊到单台）
- `prepayment_settled_amount`：累计已结转/抵扣额（二期新增列，NULL 按 0 计，纯加法）
- `prepayment_settled`：全部结转完置 True（一期售后回租出售时直接置位，语义不变——本服务跳过已置位设备）

结转规则：直线法——每月计费时结转 `q2(预付款总额 / 合同月数)`，最后一次吃尾差结清。
合同月起止缺失 → 不结转（无规则依据，不静默乱结）。余额 = 总额 − 累计已结转。
service 不 commit 铁律：只 flush，commit 在 endpoint/scheduler。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing import Billing
from app.models.device import Device
from app.models.project import Contract, Project
from app.utils.reconcile import q2


def _contract_months(c: Contract) -> int | None:
    """合同月数（含首尾月）；起止缺失 → None（不结转）。"""
    if not c.start_date or not c.end_date or c.end_date < c.start_date:
        return None
    return (c.end_date.year - c.start_date.year) * 12 + (c.end_date.month - c.start_date.month) + 1


def monthly_settlement(prepayment: Decimal, months: int) -> Decimal:
    """直线月结转额 = q2(总额/月数)。纯函数（golden 用）。"""
    return q2(prepayment / months)


def settle_for_billing(db: Session, billing: Billing, actor_id: uuid.UUID | None = None) -> Decimal | None:
    """计费钩子：按台计费生成后，对该设备做一次预付款月结转。返回本次结转额（未结转返回 None）。

    跳过条件（任一）：无设备维 / 无预付款 / 已结清（含一期回租置位）/ 合同月起止缺失。
    """
    if billing.device_id is None:
        return None
    d = db.get(Device, billing.device_id)
    if d is None or d.deleted_at is not None:
        return None
    if not d.prepayment_amount or d.prepayment_amount <= 0:
        return None
    if d.prepayment_settled:  # 一期售后回租语义：已置位 = 已结清，不再动
        return None
    c = db.get(Contract, billing.contract_id)
    if c is None:
        return None
    months = _contract_months(c)
    if months is None:
        return None

    settled = d.prepayment_settled_amount or Decimal(0)
    remaining = d.prepayment_amount - settled
    monthly = monthly_settlement(d.prepayment_amount, months)
    # 尾差收敛：剩余不足月额（零头 < 1 分视为尾差）→ 一次结清（如 1000/3：333.33+333.33+333.34）
    amt = remaining if (remaining - monthly) <= Decimal("0.01") else monthly
    if amt <= 0:
        return None
    d.prepayment_settled_amount = settled + amt
    if d.prepayment_settled_amount >= d.prepayment_amount:
        d.prepayment_settled_amount = d.prepayment_amount  # 结清即对齐总额
        d.prepayment_settled = True
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="device",
               target_id=d.id,
               after_json={"prepayment_settle": str(amt), "billing_id": str(billing.id),
                           "settled_amount": str(d.prepayment_settled_amount),
                           "settled": d.prepayment_settled})
    return amt


def prepayment_summary(db: Session, project_id=None) -> list[dict]:
    """预付款台账（聚合 devices 行，D2 单源）：总额/已结转/余额/是否结清。"""
    stmt = select(Device).where(Device.prepayment_amount > 0).order_by(Device.created_at.desc())
    if project_id:
        stmt = stmt.where(Device.project_id == project_id)
    rows = []
    for d in db.execute(stmt).scalars().all():
        settled = d.prepayment_settled_amount or Decimal(0)
        proj = db.get(Project, d.project_id)
        rows.append({
            "device_id": str(d.id), "sn": d.sn,
            "project_id": str(d.project_id), "project_name": proj.name if proj else None,
            "prepayment_amount": d.prepayment_amount,
            "settled_amount": settled,
            "remaining": d.prepayment_amount - settled,
            "settled": d.prepayment_settled,
        })
    return rows
