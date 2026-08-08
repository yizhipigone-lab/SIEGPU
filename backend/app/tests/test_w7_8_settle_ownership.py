"""W7-8 集成测试：settle_ownership 上架派生（D1 仅填 None + D2 售后回租=表内自有）。

落点 _sync_device_asset 上架分支：ownership 为 None 时由 leasing_mode 派生；
显式 ownership 永远优先（49+9 现有测试零回归）。
"""
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models.asset import Asset
from app.models.device import OffBalanceRegister
from app.models.master import EquipmentModel
from app.models.project import Project
from app.services import device_service as dsvc


def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8)
    db.add(e); db.flush(); return e


def _advance_to(db, device_id, target_stage):
    for st in dsvc.DEVICE_STAGES[:dsvc.DEVICE_STAGES.index(target_stage) + 1]:
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="进行中")
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="已完成")


def test_settle_ownership_leaseback_derives_on_balance_and_creates_card(db):
    """售后回租 ownership=None → 上架派生 表内自有 + 建资产卡（spec §2.4 先转固，非表外）。"""
    p = _project(db); e = _equipment(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))  # ownership 不传 → None
    assert d.ownership is None
    _advance_to(db, d.id, "上架")
    db.refresh(d)
    assert d.ownership == "表内自有"  # D2：售后回租上架 = 表内自有
    asset = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    assert asset.operation_status == "已转固未运营"
    # 上架不建 off_balance（回租出售才建）
    assert db.execute(select(OffBalanceRegister).where(
        OffBalanceRegister.device_id == d.id)).scalar_one_or_none() is None


def test_settle_ownership_explicit_not_overwritten(db):
    """D1：显式 ownership 永远优先——显式传 金租表外 的售后回租设备上架不被派生覆盖。"""
    p = _project(db); e = _equipment(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", ownership="金租表外",  # 显式覆盖
                           purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "上架")
    db.refresh(d)
    assert d.ownership == "金租表外"  # 显式入参优先，未翻转
    assert db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one_or_none() is None
    assert db.execute(select(OffBalanceRegister).where(
        OffBalanceRegister.device_id == d.id)).scalar_one_or_none() is not None


def test_settle_ownership_direct_lease_derives_off_balance(db):
    """直租 ownership=None → 上架派生 金租表外 + off_balance 建档（register_type=金租直租）。"""
    p = _project(db); e = _equipment(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="直租", purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "上架")
    db.refresh(d)
    assert d.ownership == "金租表外"
    reg = db.execute(select(OffBalanceRegister).where(
        OffBalanceRegister.device_id == d.id)).scalar_one()
    assert reg.register_type == "金租直租"
