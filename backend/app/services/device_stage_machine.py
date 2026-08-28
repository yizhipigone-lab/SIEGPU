"""设备状态机（一期 W3-4 设备粒度路径，自 device_service 拆出）。

- 7 节点懒初始化；device.status 物化列由节点行派生（_derive_device_status）。
- 推进副作用：资产/表外同步（device_asset_sync）、批次聚合与放款触发（device_batch，
  函数级延迟 import 避免环）、自动投保 hook（advisory，绝不阻塞）。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.billing import Billing
from app.models.device import DeviceStage
from app.services.device_asset_sync import _sync_device_asset
from app.services.device_crud import get_device_or_404

# 设备 7 节点（一期 W3-4 设备粒度新路径）
DEVICE_STAGES = ["订货", "在途", "到货", "己方压测", "上架", "客户压测", "点亮验收"]
# 节点状态机：未开始→进行中；进行中→已完成/不合格；不合格→进行中（返工）；已完成→不合格（W5-6 返工）
DEVICE_STAGE_TRANSITIONS = {
    "未开始": {"进行中"},
    "进行中": {"已完成", "不合格"},
    "不合格": {"进行中"},
    "已完成": {"不合格"},
}


def _derive_device_status(stages: list[DeviceStage]) -> str:
    """纯函数：由节点行派生 device.status 物化列。

    stages 须按 seq 升序。返回首个未「已完成」的 stage 名；全部已完成→点亮验收；无行→订货。
    「不合格」算未完成，device.status 停在该节点名（细节读行）。
    """
    if not stages:
        return "订货"
    for s in stages:
        if s.status != "已完成":
            return s.stage
    return "点亮验收"


def list_device_stages(db: Session, device_id) -> list[DeviceStage]:
    return db.execute(
        select(DeviceStage)
        .where(DeviceStage.device_id == device_id, DeviceStage.deleted_at.is_(None))
        .order_by(DeviceStage.seq)
    ).scalars().all()


def _ensure_device_stages(db: Session, device_id) -> list[DeviceStage]:
    """懒初始化：缺则建 7 行未开始；已存在直接返回（按 seq 升序）。幂等。"""
    existing = list_device_stages(db, device_id)
    if existing:
        return existing
    rows = [DeviceStage(device_id=device_id, stage=st, seq=i, status="未开始")
            for i, st in enumerate(DEVICE_STAGES, 1)]
    db.add_all(rows)
    db.flush()
    return rows


def init_device_stages(db: Session, device_id, operator_id=None) -> list[DeviceStage]:
    """显式初始化设备 7 节点（UI/批量可调；未进交付的设备无节点行）。"""
    get_device_or_404(db, device_id)
    return _ensure_device_stages(db, device_id)


def _assert_light_rework_safe(db: Session, device_id) -> None:
    """D5：点亮验收 已完成→不合格 返工前置守门。

    已有运营中资产或按台计费 → 抛 STATE_ERROR（财务副作用不可静默回退，须先红冲计费 + 处置资产）。
    表外设备（金租/转售）点亮验收不建资产 → 可自由返工；表内自有点亮即建卡 → 被拦。
    """
    has_asset = db.execute(
        select(Asset.id).where(
            Asset.device_id == device_id, Asset.operation_status == "运营中",
            Asset.deleted_at.is_(None),
        ).limit(1)
    ).scalar_one_or_none() is not None
    has_billing = db.execute(
        select(Billing.id).where(
            Billing.device_id == device_id, Billing.deleted_at.is_(None),
        ).limit(1)
    ).scalar_one_or_none() is not None
    if has_asset or has_billing:
        raise BusinessError(
            "STATE_ERROR",
            "该设备已点亮验收并建卡/计费，返工请先红冲按台计费与处置资产",
            409,
        )


def _assert_purchase_accepted(db: Session, device) -> None:
    """四期 W4 期3 硬流转#1：推进「在途」前，设备所属采购订单/批次须已有「已通过」的采购验收。
    无关联订单（order_id/batch_id 皆空，如直接建档）→ 不强制。"""
    from app.models.acceptance import AcceptanceRecord
    order_ids = [oid for oid in (device.order_id, device.batch_id) if oid]
    if not order_ids:
        return
    ok = db.execute(
        select(AcceptanceRecord.id).where(
            AcceptanceRecord.order_id.in_(order_ids),
            AcceptanceRecord.acceptance_type == "采购验收",
            AcceptanceRecord.status == "已通过",
            AcceptanceRecord.deleted_at.is_(None),
        )
    ).first()
    if not ok:
        raise BusinessError("PRECONDITION", "该设备所属采购订单尚未通过采购验收，不能登记在途发货", 409)


def advance_device_stage(db: Session, *, device_id, stage, status,
                         actual_date=None, attachment_path=None, notes=None,
                         operator_id=None):
    """推进设备单节点：校验状态机→更新行→重算 device.status 物化列→同步批次聚合状态。

    返回 (device, stage_row)。点亮验收→已完成 在 W3-4 仅置完成（按台资产/计费在 W5-6）。
    """
    # 函数级延迟 import：device_batch 顶层回本模块（advance_batch_stages→advance_device_stage），
    # 顶层互引成环；与仓库 audit_service/insurance_service 延迟 import 同模式。
    from app.services.device_batch import _maybe_trigger_disbursement_todo, _sync_batch_status

    d = get_device_or_404(db, device_id)
    # 三期 §4.4：已退货设备不可再推进（退货出库即脱离状态机）
    if d.status == "已退货":
        raise BusinessError("ILLEGAL_TRANSITION", f"设备 {d.sn} 已退货，不可再推进节点", 409)
    if stage not in DEVICE_STAGES:
        raise BusinessError("BAD_REQUEST", f"未知设备节点：{stage}", 400)
    stages = _ensure_device_stages(db, d.id)
    row = next((s for s in stages if s.stage == stage), None)
    if row is None:
        raise BusinessError("NOT_FOUND", f"设备 {d.sn} 无节点 {stage}", 404)
    allowed = DEVICE_STAGE_TRANSITIONS.get(row.status, set())
    if status not in allowed:
        raise BusinessError("ILLEGAL_TRANSITION", f"节点 {stage} 不允许 {row.status} → {status}", 409)
    # 四期 W4 期3 硬流转#1：采购验收通过 → 才能推进「在途」（发货）。无关联订单的设备不强制。
    if stage == "在途" and status in ("进行中", "已完成"):
        _assert_purchase_accepted(db, d)
    # D5：点亮验收 已完成→不合格 返工守门（有运营中资产或按台计费 → 必须先红冲/处置）
    if stage == "点亮验收" and row.status == "已完成" and status == "不合格":
        _assert_light_rework_safe(db, d.id)
    before = row.status
    row.status = status
    if actual_date is not None:
        row.actual_date = actual_date
    if attachment_path is not None:
        row.attachment_path = attachment_path
    if notes is not None:
        row.notes = notes
    d.status = _derive_device_status(stages)  # stages 已就地变更，直接派生
    db.flush()
    # W5-6：上架建卡 / 点亮激活 的资产同步（D1 两段式生命周期）
    _sync_device_asset(db, d, stage, status, actual_date, operator_id=operator_id)
    # 二期 W7-8：自动投保 hook（advisory——无配置/异常只记日志，绝不阻塞设备推进）
    try:
        from app.services import insurance_service as _ins
        if stage == "在途" and status in ("进行中", "已完成") and d.batch_id:
            _ins.maybe_auto_transport_policy(db, batch_id=d.batch_id, operator_id=operator_id)
        elif stage == "点亮验收" and status == "已完成":
            _ins.maybe_auto_property_policy(db, device=d, operator_id=operator_id)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("insurance auto-policy hook failed: device=%s stage=%s", d.id, stage)
    if d.batch_id:
        _sync_batch_status(db, d.batch_id)
        # W7-8 D3：点亮验收完成 → 批次放款达成率达阈值 → 自动建金租融资申请（幂等哨兵防二建）
        if stage == "点亮验收" and status == "已完成":
            _maybe_trigger_disbursement_todo(db, d.batch_id, operator_id)
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="device",
               target_id=d.id,
               before_json={"stage": stage, "status": before},
               after_json={"stage": stage, "status": status, "device_status": d.status})
    return d, row


def complete_device_stage(db: Session, *, device_id, stage, actual_date=None,
                          operator_id=None):
    """把设备某节点直接推到「已完成」（跨过进行中）。幂等：已完成为 no-op。

    用于销售验收勾选「上架」的联动：一次到位标记完成（含上架建卡/表外同步的资产副作用）。
    """
    d = get_device_or_404(db, device_id)
    stages = _ensure_device_stages(db, d.id)
    row = next((s for s in stages if s.stage == stage), None)
    if row is None or row.status == "已完成":
        return d, row
    if row.status != "进行中":
        advance_device_stage(db, device_id=device_id, stage=stage, status="进行中",
                             actual_date=actual_date, operator_id=operator_id)
    return advance_device_stage(db, device_id=device_id, stage=stage, status="已完成",
                                actual_date=actual_date, operator_id=operator_id)
