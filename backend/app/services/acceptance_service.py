"""验收记录 Service — 采购验收 + 销售验收。"""
import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.acceptance import AcceptanceRecord

logger = logging.getLogger(__name__)

# 设备阶段顺序（与 device_service.DEVICE_STAGES 一致），「在途」起的下标
_SHIPPED_STAGES = ("在途", "到货", "己方压测", "上架", "客户压测", "点亮验收")


def _assert_devices_shipped(db, sales_order_id) -> None:
    """四期 W4 期3 硬流转#2：销售验收前，销售批次下已挂设备须全部「在途」或更后（已发货）。
    未挂任何设备的销售订单不强制（无设备可验，保持兼容）。"""
    from app.models.device import Device
    from app.models.sales_order import SalesBatchDevice
    dev_ids = db.execute(
        select(SalesBatchDevice.device_id).where(
            SalesBatchDevice.sales_batch_id == sales_order_id,
            SalesBatchDevice.active.is_(True),
            SalesBatchDevice.deleted_at.is_(None),
        )
    ).scalars().all()
    if not dev_ids:
        return  # 未挂设备 → 不强制（兼容非批次/旧路径）
    not_shipped = db.execute(
        select(Device.sn).where(
            Device.id.in_(dev_ids),
            Device.deleted_at.is_(None),
            Device.status.notin_(_SHIPPED_STAGES),
        )
    ).scalars().all()
    if not_shipped:
        raise BusinessError(
            "PRECONDITION",
            f"尚有 {len(not_shipped)} 台设备未发货（仍在「在途」之前），不能做销售验收",
            409,
        )


def create_acceptance(db: Session, *, project_id: uuid.UUID, acceptance_type: str,
                      order_id: uuid.UUID | None = None, sales_order_id: uuid.UUID | None = None,
                      inspector: str | None = None, quantity_accepted: int = 0,
                      quantity_rejected: int = 0, notes: str | None = None,
                      shelve: bool = False) -> AcceptanceRecord:
    # 条件约束校验 [M9]
    if acceptance_type == "采购验收" and not order_id:
        raise BusinessError("VALIDATION_ERROR", "采购验收必须关联采购订单(order_id)", 422)
    if acceptance_type == "销售验收" and not sales_order_id:
        raise BusinessError("VALIDATION_ERROR", "销售验收必须关联销售订单(sales_order_id)", 422)

    # 四期 W4 期3 硬流转#2：在途发货 → 才能销售验收。销售批次已挂设备时，须全部「在途」或更后。
    if acceptance_type == "销售验收":
        _assert_devices_shipped(db, sales_order_id)

    ar = AcceptanceRecord(
        project_id=project_id, acceptance_type=acceptance_type,
        order_id=order_id, sales_order_id=sales_order_id,
        inspector=inspector, acceptance_date=date.today(),
        quantity_accepted=quantity_accepted, quantity_rejected=quantity_rejected,
        notes=notes, shelve=shelve,
    )
    db.add(ar)
    db.flush()
    return ar


def get_acceptance(db: Session, ar_id: uuid.UUID) -> AcceptanceRecord | None:
    return db.get(AcceptanceRecord, ar_id)


def list_acceptances(db: Session, *, project_id: uuid.UUID | None = None,
                     acceptance_type: str | None = None, skip=0, limit=100):
    stmt = select(AcceptanceRecord).where(AcceptanceRecord.deleted_at.is_(None))
    if project_id:
        stmt = stmt.where(AcceptanceRecord.project_id == project_id)
    if acceptance_type:
        stmt = stmt.where(AcceptanceRecord.acceptance_type == acceptance_type)
    stmt = stmt.order_by(AcceptanceRecord.created_at.desc()).offset(skip).limit(limit)
    return db.execute(stmt).scalars().all()


def _sync_shelve_for_sales_acceptance(db: Session, ar: AcceptanceRecord, operator_id=None) -> None:
    """销售验收审批通过且勾选「上架」→ 同步把订单/批次设备的上架标记完成。

    按订单类型自动判断：
    - 销售批次（已挂设备）→ 批内设备 device_stages「上架」→ 已完成（含资产卡/表外同步）
    - 旧 6 阶段（非批次销售订单）→ 同项目采购订单 delivery_stages「上架」→ 已完成
    """
    if ar.acceptance_type != "销售验收" or not ar.shelve:
        return
    from app.models.delivery import DeliveryStage, Order
    from app.models.sales_order import SalesBatchDevice, SalesOrder
    from app.services import device_service as dsvc

    so = db.get(SalesOrder, ar.sales_order_id)
    if so is None:
        return
    actual_date = ar.acceptance_date or date.today()

    device_ids = db.execute(
        select(SalesBatchDevice.device_id).where(
            SalesBatchDevice.sales_batch_id == so.id,
            SalesBatchDevice.active.is_(True),
            SalesBatchDevice.deleted_at.is_(None),
        )
    ).scalars().all()

    if device_ids:
        # 设备粒度路径：逐台推进「上架」到已完成（SAVEPOINT 隔离，单台失败不影响其余）
        ok = fail = 0
        for did in device_ids:
            try:
                with db.begin_nested():
                    dsvc.complete_device_stage(db, device_id=did, stage="上架",
                                               actual_date=actual_date, operator_id=operator_id)
                ok += 1
            except BusinessError:
                fail += 1
        if fail:
            logger.warning("shelve sync: %d/%d 台设备上架推进失败", fail, ok + fail)
    else:
        # 旧 6 阶段路径：同项目采购订单的 delivery_stages「上架」→ 已完成
        orders = db.execute(
            select(Order).where(Order.project_id == so.project_id, Order.deleted_at.is_(None))
        ).scalars().all()
        for o in orders:
            stage = db.execute(
                select(DeliveryStage).where(
                    DeliveryStage.order_id == o.id, DeliveryStage.stage == "上架",
                    DeliveryStage.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if stage is not None and stage.status != "已完成":
                stage.status = "已完成"
                stage.actual_date = actual_date
                db.flush()


def approve_acceptance(db: Session, ar: AcceptanceRecord, *,
                       quantity_accepted: int | None = None,
                       quantity_rejected: int | None = None,
                       acceptance_date: date | None = None,
                       approved_by=None) -> AcceptanceRecord:
    """验收通过。"""
    if ar.status != "待验收" and ar.status != "验收中":
        raise BusinessError("STATE_ERROR", f"当前状态 {ar.status} 不允许验收通过", 409)
    ar.status = "已通过"
    if quantity_accepted is not None:
        ar.quantity_accepted = quantity_accepted
    if quantity_rejected is not None:
        ar.quantity_rejected = quantity_rejected
    if acceptance_date:
        ar.acceptance_date = acceptance_date
    else:
        ar.acceptance_date = date.today()
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=approved_by, action="ACCEPT_APPROVE", target_type="acceptance_record",
               target_id=ar.id, after_json={"status": "已通过", "type": ar.acceptance_type,
               "accepted": ar.quantity_accepted, "rejected": ar.quantity_rejected,
               "shelve": ar.shelve})
    # W4：销售验收勾选「上架」→ 同步标记上架完成
    _sync_shelve_for_sales_acceptance(db, ar, operator_id=approved_by)
    return ar


def reject_acceptance(db: Session, ar: AcceptanceRecord, reason: str, rejected_by=None) -> AcceptanceRecord:
    """验收驳回。"""
    if ar.status not in ("待验收", "验收中"):
        raise BusinessError("STATE_ERROR", f"当前状态 {ar.status} 不允许驳回", 409)
    ar.status = "已驳回"
    ar.rejection_reason = reason
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=rejected_by, action="ACCEPT_APPROVE", target_type="acceptance_record",
               target_id=ar.id, after_json={"status": "已驳回", "reason": reason})
    return ar
