"""预付款服务（S3 收敛，D2 裁定翻盘）。

缺陷#5/#6 修复：台账以 prepayments 表为单一真源（含 登记时间/供应商/采购合同/幂等键），
与资金流水同事务落账（/capital/prepayment）；设备登记预付款自动落台账（device_id 分摊行，
payment_date 取 devices.prepayment_date，可空=待补）。devices 的 prepayment_* 字段保留为
冗余镜像（历史测试/回租语义兼容），结转同时扣设备字段与台账行。

结转规则不变：直线法——每月计费时结转 q2(预付款总额 / 合同月数)，最后一次吃尾差结清。
余额 = 台账 amount − settled_amount。
service 不 commit 铁律：只 flush，commit 在 endpoint/scheduler。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing import Billing
from app.models.device import Device
from app.models.master import Supplier
from app.models.prepayment import Prepayment
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


def _device_purchase_contract(db: Session, device: Device) -> uuid.UUID | None:
    """设备来源台账行的采购合同：设备 order → orders.contract_id（可空）。"""
    if not device.order_id:
        return None
    from app.models.delivery import Order
    o = db.get(Order, device.order_id)
    return o.contract_id if o else None


def ensure_device_ledger(db: Session, device: Device, actor_id: uuid.UUID | None = None) -> Prepayment | None:
    """设备登记/编辑预付款 → 自动落台账行（S3 缺陷#6）。

    - 无行且 prepayment_amount>0 → 建行（supplier 取设备供应商可空=待补，payment_date 取设备预付款日期）
    - 有行 → 金额/日期同步（编辑场景，K7）；金额归 0 → 保留行（金额 0 不显示于台账，结转停）
    """
    if device.deleted_at is not None:
        return None
    row = db.execute(
        select(Prepayment).where(
            Prepayment.device_id == device.id,
            Prepayment.deleted_at.is_(None),
        ).order_by(Prepayment.created_at.desc())
    ).scalars().first()
    amount = device.prepayment_amount or Decimal(0)
    if row is None:
        if amount <= 0:
            return None
        row = Prepayment(
            project_id=device.project_id, supplier_id=device.supplier_id,
            contract_id=_device_purchase_contract(db, device),
            device_id=device.id, payment_date=device.prepayment_date,
            amount=amount, settled_amount=Decimal(0),
            idempotency_key=f"device-prepay:{device.id}",
        )
        db.add(row)
        db.flush()
        from app.services import audit_service as _audit
        _audit.log(db, user_id=actor_id, action="CREATE", target_type="prepayment",
                   target_id=row.id, after_json={"device_id": str(device.id), "amount": str(amount)})
    else:
        if row.amount != amount:
            row.amount = amount
        if device.prepayment_date is not None and row.payment_date is None:
            row.payment_date = device.prepayment_date
        db.flush()
        from app.services import audit_service as _audit
        _audit.log(db, user_id=actor_id, action="UPDATE", target_type="prepayment",
                   target_id=row.id, after_json={"device_id": str(device.id), "amount": str(amount),
                                                 "payment_date": str(device.prepayment_date or "")})
    return row


def settle_for_billing(db: Session, billing: Billing, actor_id: uuid.UUID | None = None) -> Decimal | None:
    """计费钩子：按台计费生成后，对该设备做一次预付款月结转。返回本次结转额（未结转返回 None）。

    跳过条件（任一）：无设备维 / 无预付款 / 已结清（含一期回租置位）/ 合同月起止缺失。
    S3：同时扣 台账行 settled_amount（单源）+ 设备镜像字段（历史兼容）。
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
    # S3：台账行同步（单源；无行时兜底 ensure）
    row = db.execute(
        select(Prepayment).where(
            Prepayment.device_id == d.id, Prepayment.deleted_at.is_(None),
        ).order_by(Prepayment.created_at.desc())
    ).scalars().first()
    if row is None:
        row = ensure_device_ledger(db, d, actor_id=actor_id)
    if row is not None:
        row.settled_amount = min(row.amount, (row.settled_amount or Decimal(0)) + amt)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="device",
               target_id=d.id,
               after_json={"prepayment_settle": str(amt), "billing_id": str(billing.id),
                           "settled_amount": str(d.prepayment_settled_amount),
                           "settled": d.prepayment_settled})
    return amt


def prepayment_summary(db: Session, project_id=None) -> list[dict]:
    """预付款台账（S3 单源：读 prepayments 表）。行含 日期/供应商/合同/设备SN/总额/已结转/余额。"""
    stmt = (select(Prepayment)
            .where(Prepayment.deleted_at.is_(None))
            .order_by(Prepayment.payment_date.desc().nullslast(), Prepayment.created_at.desc()))
    if project_id:
        stmt = stmt.where(Prepayment.project_id == project_id)
    rows = []
    for p in db.execute(stmt).scalars().all():
        if p.amount is None or p.amount <= 0:
            continue  # 金额归 0 的编辑残留不展示
        dev = db.get(Device, p.device_id) if p.device_id else None
        proj = db.get(Project, p.project_id)
        sup = db.get(Supplier, p.supplier_id) if p.supplier_id else None
        con = db.get(Contract, p.contract_id) if p.contract_id else None
        settled = p.settled_amount or Decimal(0)
        rows.append({
            "id": str(p.id),
            "device_id": str(p.device_id) if p.device_id else None,
            "sn": dev.sn if dev else None,
            "project_id": str(p.project_id),
            "project_name": proj.name if proj else None,
            "supplier_id": str(p.supplier_id) if p.supplier_id else None,
            "supplier_name": sup.name if sup else None,
            "contract_id": str(p.contract_id) if p.contract_id else None,
            "contract_no": con.contract_no if con else None,
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
            "prepayment_amount": p.amount,
            "settled_amount": settled,
            "remaining": p.amount - settled,
            "settled": settled >= p.amount,
        })
    return rows
