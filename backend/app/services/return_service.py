"""采购退货服务（三期 §4.4）。

链路（父计划 §4.4）：退货申请（单台/批量）→ 出库确认（设备置「已退货」，此后不可再推进状态机）
→ 供应商收货（财务联动：已转固→资产减少+折旧冲回留痕；未转固→冲减在途物资〔仅留痕〕）
→ 红字发票（PAYABLE + reversal_of_id 挂原采购发票）→ 退款登记（capital_transactions IN）
→ 退款核销（payment_settlements 挂红字发票）。已付预付款 → prepayment_recover 追回额落字段。

守卫：点亮验收设备不可退（先红冲计费/处置资产——同返工守门 D5 精神）；已退货设备不可再退；
状态机强顺序（不可跳步）。service 不 commit 铁律：只 flush。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.billing import Invoice
from app.models.capital import CapitalTransaction
from app.models.device import Device
from app.models.project import Project
from app.models.return_order import ReturnOrder, ReturnOrderDevice

# 状态机（强顺序；预付款已冲回 是 供应商已收货 之后的替代终态）
_FLOW = {
    "退货申请": "已出库",
    "已出库": "供应商已收货",
    "供应商已收货": "已开红字发票",
    "已开红字发票": "已退款核销",
}
RETURN_TYPES = ("到货不合格", "压测不通过", "合同终止")


def create_return(db: Session, *, project_id, return_type: str, device_ids: list,
                  original_order_id=None, original_invoice_id=None, reason=None,
                  actor_id=None) -> ReturnOrder:
    """退货申请（单台/批量）。金额 = Σ设备 purchase_value；预付款追回额 = Σ设备剩余预付款。"""
    if return_type not in RETURN_TYPES:
        raise BusinessError("BAD_REQUEST", f"未知退货类型：{return_type}", 400)
    proj = db.get(Project, project_id)
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    if not device_ids:
        raise BusinessError("BAD_REQUEST", "退货必须包含至少一台设备", 400)
    devices = []
    for did in device_ids:
        d = db.get(Device, did)
        if not d or d.deleted_at is not None:
            raise BusinessError("NOT_FOUND", f"设备不存在：{did}", 404)
        if d.status == "已退货":
            raise BusinessError("DUPLICATE", f"设备 {d.sn} 已退货", 409)
        if d.status == "点亮验收":
            raise BusinessError("ILLEGAL_TRANSITION",
                                f"设备 {d.sn} 已点亮验收，退货请先红冲计费并处置资产", 409)
        devices.append(d)
    total = sum((d.purchase_value or Decimal(0) for d in devices), Decimal(0))
    recover = sum(
        ((d.prepayment_amount or Decimal(0)) - (d.prepayment_settled_amount or Decimal(0))
         for d in devices if not d.prepayment_settled), Decimal(0))
    ro = ReturnOrder(project_id=project_id, original_order_id=original_order_id,
                     original_invoice_id=original_invoice_id, return_type=return_type,
                     total_amount=total, prepayment_recover=recover, reason=reason,
                     created_by=actor_id)
    db.add(ro)
    db.flush()
    for d in devices:
        db.add(ReturnOrderDevice(return_order_id=ro.id, device_id=d.id,
                                 amount=d.purchase_value or Decimal(0)))
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="CREATE", target_type="return_order",
               target_id=ro.id, after_json={"return_type": return_type, "devices": len(devices),
                                            "total": str(total), "prepayment_recover": str(recover)})
    return ro


def get_return_or_404(db: Session, rid) -> ReturnOrder:
    ro = db.get(ReturnOrder, rid)
    if not ro or ro.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "退货单不存在", 404)
    return ro


def list_return_devices(db: Session, return_id) -> list[ReturnOrderDevice]:
    return list(db.execute(select(ReturnOrderDevice).where(
        ReturnOrderDevice.return_order_id == return_id)).scalars().all())


def advance_return(db: Session, rid, *, actor_id=None, transaction_date: date | None = None) -> ReturnOrder:
    """推进到下一状态（强顺序）。各步副作用见 _FLOW 注释。"""
    ro = get_return_or_404(db, rid)
    nxt = _FLOW.get(ro.status)
    if nxt is None:
        raise BusinessError("ILLEGAL_TRANSITION", f"退货单状态 {ro.status} 已是终态或不可推进", 409)
    rows = list_return_devices(db, ro.id)

    if nxt == "已出库":
        for r in rows:
            d = db.get(Device, r.device_id)
            d.status = "已退货"  # CHECK 已扩；状态机推进入口对「已退货」有守门（device_service）
    elif nxt == "供应商已收货":
        # 财务联动：已转固 → 资产减少 + 折旧冲回留痕；未转固 → 冲减在途物资（留痕）
        for r in rows:
            a = db.execute(select(Asset).where(
                Asset.device_id == r.device_id, Asset.deleted_at.is_(None))).scalar_one_or_none()
            if a is not None:
                from datetime import datetime, timezone
                a.deleted_at = datetime.now(timezone.utc)  # 资产减少（软删留痕）
                from app.services import audit_service as _audit2
                _audit2.log(db, user_id=actor_id, action="DELETE", target_type="asset",
                            target_id=a.id,
                            after_json={"reason": "退货资产减少", "return_order_id": str(ro.id),
                                        "original_value": str(a.total_original_value)})
    elif nxt == "已开红字发票":
        # 红字发票：PAYABLE + reversal_of_id 挂原采购发票
        orig = db.get(Invoice, ro.original_invoice_id) if ro.original_invoice_id else None
        contract_id = orig.contract_id if orig else None
        if contract_id is None:
            # 无原票：找项目采购合同兜底
            from app.models.project import Contract
            pc = db.execute(select(Contract).where(
                Contract.project_id == ro.project_id, Contract.type == "PURCHASE")
            ).scalars().first()
            contract_id = pc.id if pc else None
        if contract_id is None:
            raise BusinessError("BAD_REQUEST", "找不到采购合同，无法开红字发票", 400)
        from app.services import invoice_service as _isvc
        red = _isvc.create_invoice(db, contract_id=contract_id, amount=ro.total_amount,
                                   invoice_no=f"红字-{ro.id.hex[:8]}",
                                   issue_date=transaction_date or date.today())
        red.reversal_of_id = ro.original_invoice_id  # 红冲关联（None=无原票，纯红字）
        ro.red_invoice_id = red.id
    elif nxt == "已退款核销":
        if ro.red_invoice_id is None:
            raise BusinessError("BAD_REQUEST", "尚未开红字发票", 400)
        # 退款登记（供应商退款 IN）+ 退款核销（payment_settlements 挂红字发票）
        txn = CapitalTransaction(
            project_id=ro.project_id, source_type="自有资金", direction="IN",
            amount=ro.total_amount, transaction_date=transaction_date or date.today(),
            category="退货退款", note=f"退货单 {ro.id} 供应商退款",
            idempotency_key=f"return-refund:{ro.id}", created_by=actor_id,
        )
        db.add(txn)
        db.flush()
        from app.models.payment import PaymentSettlement
        db.add(PaymentSettlement(capital_transaction_id=txn.id,
                                 invoice_id=ro.red_invoice_id, amount=ro.total_amount))
        ro.refund_txn_id = txn.id

    ro.status = nxt
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="return_order",
               target_id=ro.id, after_json={"status": nxt})
    return ro


def list_returns(db: Session, project_id=None, status=None) -> list[ReturnOrder]:
    stmt = select(ReturnOrder).order_by(ReturnOrder.created_at.desc())
    if project_id:
        stmt = stmt.where(ReturnOrder.project_id == project_id)
    if status:
        stmt = stmt.where(ReturnOrder.status == status)
    return list(db.execute(stmt).scalars().all())
