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


def _fx_inherit(db: Session, c, billing_date) -> dict:
    """二期 W5-6：计费单继承合同币种；booked_rate 按计费日取汇率（最近不未来）。
    无汇率记录 → booked_rate 留 NULL（不阻断计费主流程；率缺失只影响后续汇兑计算的前置数据）。"""
    if not c.currency_code:
        return {}
    from app.services import exchange_service as _fx
    try:
        rate = _fx.get_rate(db, c.currency_code, _fx.base_currency_code(db), billing_date)
    except BusinessError:
        rate = None
    return {"currency_code": c.currency_code, "booked_rate": rate}


def generate_billing(db: Session, *, order_id, contract_id, period_index: int, billing_date,
                     created_by, idempotency_key: str | None = None) -> Billing:
    o = db.get(Order, order_id)
    if not o or o.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "订单不存在", 404)
    # 一期 W3-4 discipline ②：设备粒度订单按台计费（W5-6），禁走旧 order 维度 generate_billing。
    # 自检迭代修正：闸提到最前（D4「顶部统一过」），原置于 monthly_rent 校验之后，
    # 致 device 订单在合同缺 monthly_rent 时返回 BAD_REQUEST 而非 FLOW_TYPE_DEVICE（HTTP 抽查发现）。
    from app.services import device_service as dsvc
    dsvc.assert_legacy_path(db, o)
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
        **_fx_inherit(db, c, billing_date),
    )
    db.add(b)
    db.flush()
    from app.services import workflow_service as _wf
    _wf.after_action(db, o.project_id)
    return b


def list_billings(db: Session, contract_id=None, order_id=None, device_id=None):
    stmt = select(Billing).order_by(Billing.billing_date.desc())
    if contract_id:
        stmt = stmt.where(Billing.contract_id == contract_id)
    if order_id:
        stmt = stmt.where(Billing.order_id == order_id)
    if device_id:
        stmt = stmt.where(Billing.device_id == device_id)
    return db.execute(stmt).scalars().all()


# ============================ 一期 W5-6：按台计费（device 维度） ============================

def _device_light_on_date(db: Session, device_id):
    """device_stages 点亮验收已完成日（按台计费起点）。镜像 _light_on_date（delivery_stages 点亮）。"""
    from app.models.device import DeviceStage
    st = db.execute(
        select(DeviceStage).where(
            DeviceStage.device_id == device_id, DeviceStage.stage == "点亮验收"
        )
    ).scalar_one_or_none()
    if not st or st.status != "已完成" or st.actual_date is None:
        raise BusinessError("BAD_REQUEST", "设备尚未点亮验收，无法计费（计费起点=点亮验收日）", 400)
    return st.actual_date


def _resolve_sales_order_for_device(db: Session, device):
    """经 device.sales_contract_id 反查合同下的 SalesOrder（D3 thread；不放宽 sales_order_id NOT NULL）。

    sales_contract_id 指向合同；SalesOrder.contract_id 同属该合同。无 sales_contract_id 或无匹配 → None。
    """
    if device.sales_contract_id is None:
        return None
    from app.models.sales_order import SalesOrder
    return db.execute(
        select(SalesOrder).where(SalesOrder.contract_id == device.sales_contract_id)
        .order_by(SalesOrder.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def generate_billing_device(db: Session, *, device_id, contract_id, period_index: int,
                            billing_date, created_by, idempotency_key: str | None = None) -> Billing:
    """按台计费：金额取 device.monthly_price（不读 contract.monthly_rent）。

    - 计费起点 = device_stages 点亮验收日（首月按剩余天数比例，与订单维同算法）。
    - 金额 = billing_amount(device.monthly_price, period_index, light)（维度无关纯函数）。
    - device 维 dup-check（service 层）；DB 部分唯一索引 uq_billing_period(device_id, period_index) 兜底。
    - sales_order_id 经 _resolve_sales_order_for_device thread（D3）；order_id 取 device.order_id（可空）。
    """
    from app.models.device import Device
    d = db.get(Device, device_id)
    if not d or d.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "设备不存在", 404)
    if d.monthly_price is None:
        raise BusinessError("BAD_REQUEST", "设备未设 monthly_price，无法按台计费", 400)
    c = db.get(Contract, contract_id)
    if not c or c.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "合同不存在", 404)
    if c.type != "SALES":
        raise BusinessError("BAD_REQUEST", "按台计费需销售合同", 400)

    light = _device_light_on_date(db, device_id)
    amount = billing_amount(d.monthly_price, period_index, light)  # 维度无关：直喂 monthly_price
    ex, tax = split_tax(amount, c.tax_rate)
    if period_index == 1:
        days = days_in_month(light) - light.day + 1  # 含点亮当日
    else:
        days = days_in_month(billing_date)

    # device 维 dup-check（DB 部分唯一索引兜底，但 service 层先给清晰错误）
    existing = db.execute(
        select(Billing).where(
            Billing.device_id == device_id, Billing.period_index == period_index,
            Billing.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing:
        raise BusinessError("DUPLICATE", f"设备第 {period_index} 期已计费", 409)

    sales_order = _resolve_sales_order_for_device(db, d)
    b = Billing(
        project_id=d.project_id, contract_id=contract_id, order_id=d.order_id,  # 可空（导入设备无订单）
        device_id=device_id, sales_order_id=sales_order.id if sales_order else None,
        period_index=period_index, period_label=f"{billing_date.year}-{billing_date.month:02d}",
        billing_date=billing_date, days_in_period=days, amount=amount, amount_ex_tax=ex,
        tax_amount=tax, tax_rate=c.tax_rate, idempotency_key=idempotency_key,
        **_fx_inherit(db, c, billing_date),
    )
    db.add(b)
    db.flush()
    # 二期 W9-10（D2）：按台计费生成 → 预付款按月直线结转（无预付款/已结清/无合同月数自动跳过）
    from app.services import prepayment_service as _pp
    _pp.settle_for_billing(db, b, actor_id=created_by)
    from app.services import workflow_service as _wf
    _wf.after_action(db, d.project_id)
    return b
