"""设备 → 资产/表外台账同步（一期 W5-6 一机一卡，自 device_service 拆出）。

D1 两段式生命周期：
- 上架→已完成：表内自有建资产卡（已转固未运营）；表外走 off_balance_registers。
- 点亮验收→已完成：表内自有点亮激活（起折旧）；表外无动作（不计提折旧）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.device import Device, OffBalanceRegister
from app.services.device_crud import get_device_or_404
from app.utils.depreciation import depreciation_inputs
from app.utils.ownership import derive_ownership
from app.utils.repayment_plan import add_months


def create_off_balance_register(db: Session, *, device_id, register_type, leasing_process_id=None,
                                start_date=None, end_date=None, note=None,
                                operator_id=None) -> OffBalanceRegister:
    get_device_or_404(db, device_id)
    r = OffBalanceRegister(
        device_id=device_id, register_type=register_type, leasing_process_id=leasing_process_id,
        start_date=start_date, end_date=end_date, note=note,
    )
    db.add(r)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="CREATE", target_type="off_balance_register",
               target_id=r.id, after_json={"device_id": str(device_id), "register_type": register_type})
    return r


def list_off_balance_registers(db: Session, device_id=None):
    stmt = select(OffBalanceRegister).order_by(OffBalanceRegister.created_at.desc())
    if device_id:
        stmt = stmt.where(OffBalanceRegister.device_id == device_id)
    return db.execute(stmt).scalars().all()


# operation_status → 表外 register_type 映射（金租表外按 leasing_mode 细分、转售表外统一转售）
_OFF_BALANCE_REGISTER_TYPE = {
    "转售表外": "转售",
    "金租表外": "售后回租",  # 默认；leasing_mode='直租' 时下面覆盖为金租直租
}


def _ensure_off_balance_for_device(db: Session, device: Device, operator_id=None) -> OffBalanceRegister | None:
    """表外设备上架：写 off_balance_registers（不进 assets，避免污染折旧汇总）。幂等。"""
    existing = db.execute(select(OffBalanceRegister).where(
        OffBalanceRegister.device_id == device.id, OffBalanceRegister.deleted_at.is_(None)
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    register_type = _OFF_BALANCE_REGISTER_TYPE.get(device.ownership or "", "金租直租")
    if device.ownership == "金租表外" and device.leasing_mode == "直租":
        register_type = "金租直租"
    return create_off_balance_register(db, device_id=device.id, register_type=register_type,
                                       operator_id=operator_id)


def _create_asset_card_for_device(db: Session, *, device: Device, operator_id=None) -> Asset:
    """上架→已转固未运营 资产卡（表内自有）。折旧字段暂 None，待点亮激活填。幂等。

    守卫：device.purchase_value 必须非空（单台原值是建卡 + 后续折旧的唯一输入）。
    """
    if device.purchase_value is None:
        raise BusinessError("BAD_REQUEST", f"设备 {device.sn} 缺 purchase_value，无法建资产卡", 400)
    existing = db.execute(select(Asset).where(
        Asset.device_id == device.id, Asset.deleted_at.is_(None)
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    a = Asset(
        project_id=device.project_id, equipment_model_id=device.equipment_model_id,
        order_id=device.order_id, device_id=device.id, quantity=1,
        unit_original_value=device.purchase_value, total_original_value=device.purchase_value,
        residual_rate=Decimal("0.10"),  # 折旧字段全 None，待点亮填
        operation_status="已转固未运营", status="折旧中",
    )
    db.add(a)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="CREATE", target_type="asset",
               target_id=a.id, after_json={"device_id": str(device.id), "operation_status": "已转固未运营"})
    return a


def _activate_asset_for_device(db: Session, *, device: Device, light_on_date: date,
                               operator_id=None) -> Asset:
    """点亮验收→运营中：填折旧字段 + start_date + operation_status='运营中'。幂等。

    若 device 跳过上架建卡直接进点亮（容错），现建一张并立即激活。
    """
    if device.purchase_value is None:
        raise BusinessError("BAD_REQUEST", f"设备 {device.sn} 缺 purchase_value，无法激活折旧", 400)
    a = db.execute(select(Asset).where(
        Asset.device_id == device.id, Asset.deleted_at.is_(None)
    )).scalar_one_or_none()
    if a is None:
        a = _create_asset_card_for_device(db, device=device, operator_id=operator_id)
    if a.operation_status == "运营中":
        return a  # 幂等：重复推进点亮不重算
    dep = depreciation_inputs(device.purchase_value)
    a.residual_value = dep["residual_value"]
    a.depreciable_value = dep["depreciable_value"]
    a.annual_depreciation = dep["annual_depreciation"]
    a.monthly_depreciation = dep["monthly_depreciation"]
    a.start_date = light_on_date
    a.end_date = add_months(light_on_date, dep["months"])
    a.operation_status = "运营中"
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="asset",
               target_id=a.id,
               after_json={"operation_status": "运营中", "start_date": str(light_on_date)})
    return a


def _sync_device_asset(db: Session, device: Device, stage: str, status: str,
                       actual_date: date | None, operator_id=None) -> None:
    """advance_device_stage 的资产同步派发（D1 两段式生命周期）。

    - 上架→已完成：表内自有建资产卡（已转固未运营）；表外走 off_balance_registers。
    - 点亮验收→已完成：表内自有点亮激活（起折旧）；表外无动作（不计提折旧）。
    其余节点不动资产。ownership 未设置时不建卡（数据质量由导入/校验把关，非本函数职责）。
    """
    if stage == "上架" and status == "已完成":
        # W7-8 D1 settle_ownership：ownership 为 None 时由 leasing_mode 派生（仅填 None，
        # 显式入参永远优先 → 49+9 现有设备测试零回归）。售后回租 → 表内自有（先转固，非表外）。
        if device.ownership is None:
            device.ownership = derive_ownership(device.leasing_mode)
            if device.ownership is not None:
                db.flush()
        if device.ownership == "表内自有":
            _create_asset_card_for_device(db, device=device, operator_id=operator_id)
        elif device.ownership in ("金租表外", "转售表外"):
            _ensure_off_balance_for_device(db, device, operator_id=operator_id)
    elif stage == "点亮验收" and status == "已完成" and actual_date is not None:
        if device.ownership == "表内自有":
            _activate_asset_for_device(db, device=device, light_on_date=actual_date,
                                       operator_id=operator_id)
