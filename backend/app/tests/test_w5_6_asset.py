"""一期 W5-6 测试（Phase A）：一机一卡资产 + 转固/运营分离。

advance_device_stage 的资产同步副作用（D1 两段式生命周期）：
- 上架→已完成：表内自有建资产卡（operation_status=已转固未运营，折旧字段 None）；表外走 off_balance_registers
- 点亮验收→已完成：表内自有点亮激活（填折旧 + operation_status=运营中）
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.delivery import Order
from app.models.device import Device, OffBalanceRegister
from app.models.master import EquipmentModel
from app.models.project import Project
from app.services import asset_service as asvc
from app.services import device_service as svc
from app.services import report_service as rsvc


def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8); db.add(e); db.flush(); return e


def _device(db, p=None, e=None, **kw):
    p = p or _project(db); e = e or _equipment(db)
    return svc.create_device(db, project_id=p.id, equipment_model_id=e.id, **kw)


def _advance_through(db, device_id, target_stage, actual_date=date(2026, 9, 15)):
    """推进 device 各节点 进行中→已完成，直到 target_stage（含）完成。"""
    for st in svc.DEVICE_STAGES[:svc.DEVICE_STAGES.index(target_stage) + 1]:
        svc.advance_device_stage(db, device_id=device_id, stage=st, status="进行中")
        svc.advance_device_stage(db, device_id=device_id, stage=st, status="已完成",
                                 actual_date=actual_date)


# ---------- 上架建卡 ----------

def test_create_asset_card_on_shelf_for_on_balance_device(db):
    d = _device(db, ownership="表内自有", purchase_value=Decimal("960000"))
    _advance_through(db, d.id, "上架")
    a = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    assert a.operation_status == "已转固未运营"
    assert a.start_date is None and a.end_date is None       # 折旧字段暂空
    assert a.monthly_depreciation is None
    assert a.quantity == 1
    assert a.total_original_value == Decimal("960000.00") and a.unit_original_value == Decimal("960000.00")
    assert a.device_id == d.id


def test_off_balance_register_created_on_shelf_for_off_balance_device(db):
    d = _device(db, ownership="金租表外", leasing_mode="直租", purchase_value=Decimal("960000"))
    _advance_through(db, d.id, "上架")
    # 不进 assets
    assert db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one_or_none() is None
    # 进 off_balance_registers
    r = db.execute(select(OffBalanceRegister).where(OffBalanceRegister.device_id == d.id)).scalar_one()
    assert r.register_type == "金租直租"  # leasing_mode=直租 → 金租直租


def test_off_balance_register_resale_type(db):
    d = _device(db, ownership="转售表外", purchase_value=Decimal("960000"))
    _advance_through(db, d.id, "上架")
    r = db.execute(select(OffBalanceRegister).where(OffBalanceRegister.device_id == d.id)).scalar_one()
    assert r.register_type == "转售"


def test_purchase_value_required_for_card_creation(db):
    d = _device(db, ownership="表内自有", purchase_value=None)
    with pytest.raises(BusinessError) as exc:  # 缺 purchase_value，推进到上架建卡时抛
        _advance_through(db, d.id, "上架")
    assert exc.value.detail["code"] == "BAD_REQUEST"  # code 存于 detail 字典


# ---------- 点亮激活 ----------

def test_activate_asset_on_light_on_fills_depreciation(db):
    from app.utils.depreciation import depreciation_inputs
    d = _device(db, ownership="表内自有", purchase_value=Decimal("960000"))
    _advance_through(db, d.id, "点亮验收", actual_date=date(2026, 9, 15))
    a = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    assert a.operation_status == "运营中"
    assert a.start_date == date(2026, 9, 15)
    dep = depreciation_inputs(Decimal("960000"))
    assert a.monthly_depreciation == dep["monthly_depreciation"]
    assert a.end_date == date(2031, 9, 15)  # +60 月（5 年）


def test_activate_asset_idempotent(db):
    """点亮激活幂等：直接二次调 _activate 不重算、不重建。"""
    d = _device(db, ownership="表内自有", purchase_value=Decimal("960000"))
    _advance_through(db, d.id, "点亮验收")
    a1 = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    a2 = svc._activate_asset_for_device(db, device=d, light_on_date=date(2026, 9, 15))
    assert a1.id == a2.id                       # 同一张卡
    assert db.execute(select(Asset).where(Asset.device_id == d.id)).scalars().all() == [a1]  # 仍 1 行


# ---------- 一机一卡唯一约束 ----------

def test_asset_card_per_device_unique(db):
    """同 device_id 第二张 active Asset 触发部分唯一索引（DB 兜底）。"""
    d = _device(db, ownership="表内自有", purchase_value=Decimal("960000"))
    _advance_through(db, d.id, "上架")
    dup = Asset(project_id=d.project_id, equipment_model_id=d.equipment_model_id,
                device_id=d.id, quantity=1, unit_original_value=Decimal("1"),
                total_original_value=Decimal("1"), operation_status="已转固未运营")
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.flush()


# ---------- NULL 消费点 ----------

def test_depreciation_schedule_raises_when_not_operating(db):
    d = _device(db, ownership="表内自有", purchase_value=Decimal("960000"))
    _advance_through(db, d.id, "上架")
    a = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    with pytest.raises(BusinessError):  # 未运营卡无折旧明细
        asvc.depreciation_schedule(db, a.id)


def test_report_service_skips_none_monthly_depreciation(db):
    """项目下混合「未运营卡(None) + 已运营卡」，project_overview 不抛且求和正确。"""
    p = _project(db)
    # 未运营卡（None monthly）
    d1 = _device(db, p=p, ownership="表内自有", purchase_value=Decimal("960000"))
    _advance_through(db, d1.id, "上架")
    # 已运营卡
    d2 = _device(db, p=p, ownership="表内自有", purchase_value=Decimal("1200000"))
    _advance_through(db, d2.id, "点亮验收")
    a2 = db.execute(select(Asset).where(Asset.device_id == d2.id)).scalar_one()

    rows = rsvc.project_overview(db)
    row = next(r for r in rows if r["project_id"] == str(p.id))
    assert row["monthly_depreciation"] == a2.monthly_depreciation  # 只算运营中那张
