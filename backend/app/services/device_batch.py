"""设备批次管理 + 金租放款联动（自 device_service 拆出）。

- 批次纪律：同一台设备全局仅一条 active batch_devices 记录（service 校验 + 部分唯一索引兜底）；
  移出仅限上架前（订货/在途/到货/己方压测）；批次 flow_type 首次判定后固化，只升不降。
- 放款联动：点亮达成率阈值触发自动建金租融资申请（幂等哨兵防二建）。
"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.delivery import Order
from app.models.device import BatchDevice, Device, DeviceStage
from app.models.leasing import LeasingProcess
from app.models.master import Supplier
from app.models.project import Project
from app.services.device_crud import get_device_or_404, list_devices
from app.services.device_stage_machine import DEVICE_STAGES, advance_device_stage
from app.utils.disbursement import reached_threshold

# 批次移出允许的节点（seq<5 上架之前）
EARLY_STAGES = {"订货", "在途", "到货", "己方压测"}

# 设备粒度 flow_type 集合（防双计闸用）——走 device_stages，禁走旧 6 节点
DEVICE_FLOW_TYPES = {"batch", "device", "transfer-resale"}


def _active_batch_row(db: Session, device_id) -> BatchDevice | None:
    return db.execute(
        select(BatchDevice).where(BatchDevice.device_id == device_id, BatchDevice.active.is_(True))
    ).scalars().first()


def add_to_batch(db: Session, *, device_id, batch_id, operator_id=None) -> BatchDevice:
    """设备挂入批次。守卫：批次订单存在；设备当前无 active 批次记录。"""
    d = get_device_or_404(db, device_id)
    batch = db.get(Order, batch_id)
    if not batch or batch.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "批次订单不存在", 404)
    existing = _active_batch_row(db, device_id)
    if existing:
        raise BusinessError("DUPLICATE", "设备已在批次中，不能重复挂载", 409)
    if not batch.is_batch:
        batch.is_batch = True
    if batch.flow_type is None:  # 首次判定固化，只升不降
        batch.flow_type = "batch"
    bd = BatchDevice(batch_id=batch_id, device_id=device_id, action="加入", active=True,
                     operated_by=operator_id)
    db.add(bd)
    d.batch_id = batch_id
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="device",
               target_id=d.id, after_json={"batch_id": str(batch_id), "batch_action": "加入"})
    return bd


def remove_from_batch(db: Session, *, device_id, operator_id=None) -> BatchDevice:
    """设备移出批次。守卫：仅上架前节点允许（订货/在途/到货/己方压测）；flow_type 不回退。"""
    d = get_device_or_404(db, device_id)
    if d.status not in EARLY_STAGES:
        raise BusinessError("ILLEGAL_STATE", f"设备已进入「{d.status}」节点，不允许移出批次", 409)
    active = _active_batch_row(db, device_id)
    if not active:
        raise BusinessError("NOT_FOUND", "设备当前不在任何批次中", 404)
    active.active = False
    out = BatchDevice(batch_id=active.batch_id, device_id=device_id, action="移出", active=False,
                      operated_by=operator_id)
    db.add(out)
    d.batch_id = None
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="device",
               target_id=d.id, after_json={"batch_id": str(active.batch_id), "batch_action": "移出"})
    return out


def list_batch_devices(db: Session, batch_id=None, device_id=None):
    stmt = select(BatchDevice).order_by(BatchDevice.created_at.desc())
    if batch_id:
        stmt = stmt.where(BatchDevice.batch_id == batch_id)
    if device_id:
        stmt = stmt.where(BatchDevice.device_id == device_id)
    return db.execute(stmt).scalars().all()


def advance_batch_stages(db: Session, *, batch_id, stage, status,
                         actual_date=None, attachment_path=None, notes=None,
                         operator_id=None) -> dict:
    """批量推进：批内所有 active 设备推进同一节点。返回 {ok, fail}（失败=状态机拒绝等）。"""
    dev_ids = [bd.device_id for bd in db.execute(
        select(BatchDevice).where(
            BatchDevice.batch_id == batch_id,
            BatchDevice.active.is_(True),
            BatchDevice.deleted_at.is_(None),
        )
    ).scalars().all()]
    ok = fail = 0
    for did in dev_ids:
        try:
            # W5-6 HIGH 修复：每台用 SAVEPOINT 隔离。_sync_device_asset 可能在 row.status 已 flush
            # 之后抛错（如表内自有设备缺 purchase_value），不隔离会让失败台的“已完成”节点随端点
            # commit 落库却无资产卡（“完成无卡”悬挂态，无法重推）。begin_nested 失败回滚到 savepoint
            # （只回滚这台的 flush，含 audit 与工作流自动推进），成功则释放——批内其余设备不受影响。
            with db.begin_nested():
                advance_device_stage(db, device_id=did, stage=stage, status=status,
                                     actual_date=actual_date, attachment_path=attachment_path,
                                     notes=notes, operator_id=operator_id)
            ok += 1
        except BusinessError:
            fail += 1
    return {"ok": ok, "fail": fail}


def _aggregate_batch_status(db: Session, batch_id) -> str | None:
    """批内设备状态聚合：全点亮验收→已点亮；否则取瓶颈（进度最靠前设备所在节点名）。"""
    devs = list_devices(db, batch_id=batch_id)
    if not devs:
        return None
    if all(d.status == "点亮验收" for d in devs):
        return "已点亮"
    seqs = [DEVICE_STAGES.index(d.status) for d in devs if d.status in DEVICE_STAGES]
    return DEVICE_STAGES[min(seqs)] if seqs else "订货"


def _sync_batch_status(db: Session, batch_id):
    """把聚合状态写入 orders.batch_status 独立字段（不复用 orders.status，审计 A3）。"""
    batch = db.get(Order, batch_id)
    if batch is not None:
        batch.batch_status = _aggregate_batch_status(db, batch_id)
        db.flush()


# ============================ 一期 W7-8：放款条件联动 ============================

def _batch_light_completion(db: Session, batch_id) -> tuple[int, int]:
    """批次点亮达成率（lit, total）。total=批内未删设备数；lit=其中点亮验收已完成的。

    与 _aggregate_batch_status（字符串聚合）正交：纯数值派生，不存储（D3）。
    返工（已完成→不合格）会让该设备点亮行离开 已完成 → lit 自然下降。
    """
    dev_ids = [r[0] for r in db.execute(
        select(Device.id).where(
            Device.batch_id == batch_id, Device.deleted_at.is_(None)
        )
    ).all()]
    total = len(dev_ids)
    if total == 0:
        return 0, 0
    lit = db.execute(
        select(func.count()).select_from(DeviceStage).where(
            DeviceStage.device_id.in_(dev_ids),
            DeviceStage.stage == "点亮验收",
            DeviceStage.status == "已完成",
            DeviceStage.deleted_at.is_(None),
        )
    ).scalar_one()
    return lit, total


def _resolve_project_leasing_supplier(db: Session, project_id):
    """解析放款金租机构：①项目最近 leasing_process.supplier_id；②否则 is_leasing_org 首条；③都无→None。"""
    recent = db.execute(
        select(LeasingProcess.supplier_id).where(
            LeasingProcess.project_id == project_id, LeasingProcess.deleted_at.is_(None)
        ).order_by(LeasingProcess.created_at.desc()).limit(1)
    ).first()
    if recent is not None:
        return recent[0]
    s = db.execute(
        select(Supplier.id).where(
            Supplier.is_leasing_org.is_(True), Supplier.deleted_at.is_(None)
        ).order_by(Supplier.created_at.asc()).limit(1)
    ).first()
    return s[0] if s is not None else None


def _ensure_disbursement_leasing_process(db: Session, batch: Order, operator_id=None):
    """达阈值自动建金租融资申请（D4 零改复用 leasing_service.create_process）。

    - 金租机构缺失 → 跳过 + 记审计（靠向导 get_my_tasks 待办暴露，操作员手补 supplier）。
    - total_amount = Σ 批内 devices.purchase_value；financing_type 按 proj.leasing_mode 派生。
    返回 LeasingProcess 或 None（跳过）。
    """
    from app.services import audit_service as _audit
    from app.services import leasing_service as _lsvc

    supplier_id = _resolve_project_leasing_supplier(db, batch.project_id)
    if supplier_id is None:  # M4：无金租机构静默跳过（不抛错、不阻塞点亮完成）
        _audit.log(db, user_id=operator_id, action="UPDATE", target_type="order",
                   target_id=batch.id,
                   after_json={"disbursement_skip_reason": "no_funding_supplier"})
        return None
    total_amount = db.execute(
        select(func.coalesce(func.sum(Device.purchase_value), 0)).where(
            Device.batch_id == batch.id, Device.deleted_at.is_(None)
        )
    ).scalar_one() or Decimal("0")
    proj = db.get(Project, batch.project_id)
    leasing_mode = proj.leasing_mode if proj is not None else None
    financing_type = "金租直租" if leasing_mode == "直租" else "金租回租"
    proc = _lsvc.create_process(db, project_id=batch.project_id, supplier_id=supplier_id,
                                total_amount=total_amount, leasing_mode=leasing_mode,
                                financing_type=financing_type)
    return proc


def _maybe_trigger_disbursement_todo(db: Session, batch_id, operator_id=None):
    """点亮完成钩子：达阈值且未建过 → 自动建 leasing_process 并写幂等哨兵。

    哨兵 = orders.disbursement_todo_process_id（首次达阈值写一次）。
    返工后 pct 下降但哨兵不回退（leasing_process 是已落单业务单据，走审批驳回不机械删——不对称已记录）。
    """
    batch = db.get(Order, batch_id)
    if batch is None or batch.deleted_at is not None:
        return
    if batch.disbursement_todo_process_id is not None:  # 幂等：已建过直接返回
        return
    lit, total = _batch_light_completion(db, batch_id)
    if not reached_threshold(lit, total, batch.disbursement_threshold_pct):
        return
    proc = _ensure_disbursement_leasing_process(db, batch, operator_id=operator_id)
    if proc is not None:
        batch.disbursement_todo_process_id = proc.id
        db.flush()


def resolve_flow_type(db: Session, order: Order) -> str | None:
    """判定订单交付路径。只升不降：flow_type 已固化直接返回；否则以 devices.batch_id 关联为准。

    返回 None=旧 6 节点路径；返回 batch/device/transfer-resale=设备粒度路径。
    """
    if order.flow_type is not None:
        return order.flow_type
    linked = db.execute(
        select(Device.id).where(Device.batch_id == order.id, Device.deleted_at.is_(None)).limit(1)
    ).scalar_one_or_none()
    if linked is not None:
        order.flow_type = "batch"  # 设备挂入即视为批次载体，固化
        db.flush()
        return order.flow_type
    # M-1：单台订单经 order_id 直连设备（非批次挂载）→ device 路径
    attached = db.execute(
        select(Device.id).where(Device.order_id == order.id, Device.deleted_at.is_(None)).limit(1)
    ).scalar_one_or_none()
    if attached is not None:
        order.flow_type = "device"
        db.flush()
        return order.flow_type
    return None


def assert_legacy_path(db: Session, order: Order) -> None:
    """防双计闸（discipline ②）：设备粒度订单禁止走旧 6 节点入口（advance_stage/light_on/generate_billing）。

    is_batch 是硬信号，独立于设备是否已挂（防 batch 订单在设备挂入前调旧入口致 500）。
    """
    if order.is_batch or resolve_flow_type(db, order) in DEVICE_FLOW_TYPES:
        raise BusinessError(
            "FLOW_TYPE_DEVICE",
            "设备粒度订单请走设备路径（device_stages），不支持旧 6 节点操作",
            409,
        )
