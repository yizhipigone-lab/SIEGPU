"""保险管理测试（二期 W7-8）：配置/保单 CRUD + 价值占比分摊 golden + 自动投保（在途/点亮）
+ 点亮前归集原值硬约束 + 摊销计划 + 理赔 + 续保 alert。

分摊/摊销用 golden 真值追值（末台/末月吃尾差，Σ 精确）；归集窗口约束是折旧污染防线（计划 W7-8 硬约束）。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.delivery import Order
from app.models.device import Device
from app.models.insurance import InsurancePolicy
from app.models.master import EquipmentModel
from app.models.project import Project
from app.services import alert_service, device_service as dsvc
from app.services import insurance_service as svc


def _project(db) -> Project:
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def _equipment(db) -> EquipmentModel:
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush(); return e


def _device(db, p, e, purchase_value=None):
    return dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                              purchase_value=purchase_value, ownership="表内自有")


def _batch(db, p, e) -> Order:
    b = Order(project_id=p.id, equipment_model_id=e.id, quantity=1,
              unit_price=Decimal("1"), total_amount=Decimal("1"), batch_name=f"批次-{uuid.uuid4().hex[:4]}")
    db.add(b); db.flush(); return b


def _advance_through(db, device_id, target_stage, actual_date=date(2026, 9, 15)):
    for st in dsvc.DEVICE_STAGES[:dsvc.DEVICE_STAGES.index(target_stage) + 1]:
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="进行中")
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="已完成",
                                  actual_date=actual_date)


def _policies(db):
    return db.execute(select(InsurancePolicy)).scalars().all()


# ------------------------------ 配置 ------------------------------

def test_config_crud_and_duplicate(db):
    c = svc.create_config(db, policy_type="运输险", default_rate=Decimal("0.001"),
                          insured_ratio=Decimal("1"), cost_allocation="资产原值")
    assert c.id is not None
    with pytest.raises(BusinessError):  # 险种唯一
        svc.create_config(db, policy_type="运输险", default_rate=Decimal("0.002"))
    with pytest.raises(BusinessError):  # 未知险种
        svc.create_config(db, policy_type="盗抢险")


# ------------------------------ 分摊 golden ------------------------------

def test_manual_policy_allocation_golden(db):
    """2 台价值 60万/40万，保额 100万 × 费率 0.001 = 保费 1000.00 → 分摊 600.00/400.00。"""
    p, e = _project(db), _equipment(db)
    d1 = _device(db, p, e, Decimal("600000"))
    d2 = _device(db, p, e, Decimal("400000"))
    pol = svc.create_policy(db, project_id=p.id, policy_type="财产险",
                            device_ids=[d1.id, d2.id], insured_amount=Decimal("1000000"),
                            premium_rate=Decimal("0.001"), cost_allocation="资产原值")
    assert pol.premium_amount == Decimal("1000.00")
    rows = svc.list_policy_devices(db, pol.id)
    assert len(rows) == 2
    by_id = {r.device_id: r.allocated_amount for r in rows}
    assert by_id[d1.id] == Decimal("600.00") and by_id[d2.id] == Decimal("400.00")
    assert sum(by_id.values()) == Decimal("1000.00")  # Σ 精确 = 保费


def test_allocation_remainder_last_device(db):
    """尾差兜底：1000 分 3 台等值 → 333.33/333.33/333.34，Σ 精确 1000.00。"""
    ids = [uuid.uuid4() for _ in range(3)]
    out = svc.allocate_by_value([(i, Decimal("100")) for i in ids], Decimal("1000"))
    shares = [s for _, s in out]
    assert shares == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert sum(shares) == Decimal("1000.00")


# ------------------------------ 自动投保（advisory hooks） ------------------------------

def test_auto_transport_policy_on_in_transit(db):
    """批次设备进「在途」→ 自动建运输险（待确认），按批次总价值×比例；二次推进幂等不重复建。"""
    svc.create_config(db, policy_type="运输险", default_rate=Decimal("0.001"),
                      insured_ratio=Decimal("1"), cost_allocation="资产原值")
    p, e = _project(db), _equipment(db)
    b = _batch(db, p, e)
    d1 = _device(db, p, e, Decimal("600000"))
    d2 = _device(db, p, e, Decimal("400000"))
    dsvc.add_to_batch(db, device_id=d1.id, batch_id=b.id)
    dsvc.add_to_batch(db, device_id=d2.id, batch_id=b.id)
    dsvc.advance_device_stage(db, device_id=d1.id, stage="在途", status="进行中")
    pols = _policies(db)
    assert len(pols) == 1
    pol = pols[0]
    assert pol.policy_type == "运输险" and pol.status == "待确认" and pol.trigger_event == "在途"
    assert pol.insured_amount == Decimal("1000000.00")  # (60万+40万)×1
    assert pol.premium_amount == Decimal("1000.00")
    assert len(svc.list_policy_devices(db, pol.id)) == 2  # 批内两台都覆盖
    # 幂等：第二台也进在途 → 不重复建
    dsvc.advance_device_stage(db, device_id=d2.id, stage="在途", status="进行中")
    assert len(_policies(db)) == 1


def test_no_config_no_auto_policy(db):
    """无投保配置 → 推进不产生任何保单（零回归：存量推进路径行为不变）。"""
    p, e = _project(db), _equipment(db)
    b = _batch(db, p, e)
    d = _device(db, p, e, Decimal("960000"))
    dsvc.add_to_batch(db, device_id=d.id, batch_id=b.id)
    dsvc.advance_device_stage(db, device_id=d.id, stage="在途", status="进行中")
    assert _policies(db) == []


def test_auto_property_policy_on_light(db):
    """点亮验收完成 → 单台财产险；直接重复调用钩子幂等（每台一张）。"""
    svc.create_config(db, policy_type="财产险", default_rate=Decimal("0.002"),
                      insured_ratio=Decimal("1"), cost_allocation="长期待摊")
    p, e = _project(db), _equipment(db)
    d = _device(db, p, e, Decimal("960000"))
    _advance_through(db, d.id, "点亮验收")
    pols = _policies(db)
    assert len(pols) == 1
    pol = pols[0]
    assert pol.policy_type == "财产险" and pol.trigger_event == "点亮"
    assert pol.insured_amount == Decimal("960000.00")
    assert pol.premium_amount == Decimal("1920.00")  # 960000 × 0.002
    assert svc.maybe_auto_property_policy(db, device=db.get(Device, d.id)) is None  # 幂等


# ------------------------------ 归集硬约束（点亮前窗口） ------------------------------

def test_collect_to_asset_pre_lit(db):
    """点亮前（已转固未运营）：保费归集进资产原值；collected_at 幂等，重复归集被拒。"""
    p, e = _project(db), _equipment(db)
    d = _device(db, p, e, Decimal("960000"))
    _advance_through(db, d.id, "上架")  # 建卡：已转固未运营
    pol = svc.create_policy(db, project_id=p.id, policy_type="财产险", device_ids=[d.id],
                            insured_amount=Decimal("960000"), premium_rate=Decimal("0.002"),
                            cost_allocation="资产原值")
    svc.collect_to_asset(db, pol.id)
    a = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    assert a.total_original_value == Decimal("961920.00")  # 960000 + 1920
    assert a.unit_original_value == Decimal("961920.00")
    assert svc.get_policy_or_404(db, pol.id).collected_at is not None
    with pytest.raises(BusinessError):  # 幂等：不可重复进原值
        svc.collect_to_asset(db, pol.id)
    a2 = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    assert a2.total_original_value == Decimal("961920.00")  # 未被二次累加


def test_collect_post_lit_rejected(db):
    """点亮后（运营中）：归集原值被硬拒（防折旧污染），资产原值不变。"""
    p, e = _project(db), _equipment(db)
    d = _device(db, p, e, Decimal("960000"))
    pol = svc.create_policy(db, project_id=p.id, policy_type="财产险", device_ids=[d.id],
                            insured_amount=Decimal("960000"), premium_rate=Decimal("0.002"),
                            cost_allocation="资产原值")
    _advance_through(db, d.id, "点亮验收")  # 运营中
    with pytest.raises(BusinessError) as exc:
        svc.collect_to_asset(db, pol.id)
    assert "长期待摊" in str(exc.value)
    a = db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one()
    assert a.total_original_value == Decimal("960000.00")  # 原值未被污染


# ------------------------------ 摊销 / 理赔 / 续保 alert ------------------------------

def test_amortization_golden(db):
    """摊销 golden：1200/12 月 = 100×12；1000/3 → 333.33/333.33/333.34，Σ 精确。"""
    rows = svc.amortization_schedule(Decimal("1200"), 12)
    assert len(rows) == 12 and all(r["amount"] == Decimal("100.00") for r in rows)
    rows = svc.amortization_schedule(Decimal("1000"), 3)
    assert [r["amount"] for r in rows] == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert sum(r["amount"] for r in rows) == Decimal("1000.00")
    with pytest.raises(BusinessError):
        svc.amortization_schedule(Decimal("1000"), 0)


def test_register_claim(db):
    p, e = _project(db), _equipment(db)
    d = _device(db, p, e, Decimal("960000"))
    pol = svc.create_policy(db, project_id=p.id, policy_type="财产险", device_ids=[d.id],
                            insured_amount=Decimal("960000"), premium_rate=Decimal("0.002"))
    svc.confirm_policy(db, pol.id)
    svc.register_claim(db, pol.id, claim_date=date(2026, 8, 12), amount=Decimal("5000"),
                       description="运输磕碰")
    pol = svc.get_policy_or_404(db, pol.id)
    assert pol.status == "理赔中"
    assert len(pol.claims) == 1 and pol.claims[0]["amount"] == "5000"


def test_expiring_policy_alert(db):
    """已生效保单 30 天内到期 → compute_alerts 产出 POLICY_EXPIRING（续保提醒）。"""
    p, e = _project(db), _equipment(db)
    d = _device(db, p, e, Decimal("960000"))
    pol = svc.create_policy(db, project_id=p.id, policy_type="财产险", device_ids=[d.id],
                            insured_amount=Decimal("960000"), premium_rate=Decimal("0.002"),
                            start_date=date.today() - timedelta(days=335),
                            end_date=date.today() + timedelta(days=20))
    svc.confirm_policy(db, pol.id)
    alerts = alert_service.compute_alerts(db)
    mine = [a for a in alerts if a["code"] == "POLICY_EXPIRING" and a.get("ref_id") == str(pol.id)]
    assert len(mine) == 1 and "20 天后到期" in mine[0]["message"]
