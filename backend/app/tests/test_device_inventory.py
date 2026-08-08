"""设备可租库存看板（F2）聚合测试。

口径（仅「表内自有」设备参与自营出租；金租/转售表外不参与）：
- 在租：status=点亮验收 且 存在未红冲按台计费
- 可租：status=点亮验收 且 无未红冲计费
- 待交付：status in (订货/在途/到货/己方压测/上架/客户压测)
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.billing import Billing
from app.models.device import Device
from app.models.master import Customer, EquipmentModel
from app.models.project import Project
from app.services import contract_service as csvc
from app.services import device_service as dsvc


def _model(db, name="H100"):
    e = EquipmentModel(name=name, category="大卡", gpu_count=8)
    db.add(e); db.flush(); return e


def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def _contract(db, project):
    cust = Customer(name="租户X"); db.add(cust); db.flush()
    return csvc.create_contract(db, project_id=project.id, type="SALES", party_id=cust.id,
                                amount=Decimal("1000"), tax_rate=Decimal("0.13"))


def _dev(db, project, model, status, ownership="表内自有"):
    d = Device(sn=f"GPU-{uuid.uuid4().hex[:12]}", project_id=project.id,
               equipment_model_id=model.id, status=status, ownership=ownership)
    db.add(d); db.flush(); return d


def _billing(db, device, contract, status="未开"):
    db.add(Billing(
        project_id=device.project_id, contract_id=contract.id, device_id=device.id,
        period_index=1, period_label="2026-01", billing_date=date(2026, 1, 31),
        days_in_period=31, amount=Decimal("113"), amount_ex_tax=Decimal("100"),
        tax_amount=Decimal("13"), tax_rate=Decimal("0.13"), status=status,
    )); db.flush()


def test_inventory_buckets_three_way(db):
    """同一型号 3 台表内自有设备：在租 / 可租 / 待交付 各一。"""
    p = _project(db); m = _model(db); c = _contract(db, p)
    rented = _dev(db, p, m, "点亮验收")          # 已点亮 + 有计费 → 在租
    avail = _dev(db, p, m, "点亮验收")           # 已点亮 + 无计费 → 可租
    _dev(db, p, m, "到货")                       # 未点亮 → 待交付
    _billing(db, rented, c, status="未开")

    rows = dsvc.inventory_summary(db)
    row = next(r for r in rows if r["model_name"] == "H100")
    assert row["total"] == 3
    assert row["rented"] == 1
    assert row["available"] == 1
    assert row["pending"] == 1


def test_inventory_excludes_offbalance(db):
    """金租表外设备即便已点亮也不计入自营库存（不参与自营出租）。"""
    p = _project(db); m = _model(db, name="A100"); c = _contract(db, p)
    _dev(db, p, m, "点亮验收", ownership="金租表外")   # 表外 → 排除
    _dev(db, p, m, "点亮验收", ownership="表内自有")   # 表内 → 可租

    rows = dsvc.inventory_summary(db)
    row = next(r for r in rows if r["model_name"] == "A100")
    assert row["total"] == 1            # 只数表内
    assert row["available"] == 1
    assert row["rented"] == 0


def test_inventory_reversed_billing_is_available(db):
    """已红冲计费不算在租——设备回到可租状态（红冲剔除）。"""
    p = _project(db); m = _model(db, name="B100"); c = _contract(db, p)
    d = _dev(db, p, m, "点亮验收")
    _billing(db, d, c, status="已红冲")   # 红冲 → 不算在租

    rows = dsvc.inventory_summary(db)
    row = next(r for r in rows if r["model_name"] == "B100")
    assert row["rented"] == 0
    assert row["available"] == 1


def test_inventory_groups_by_model(db):
    """两个型号各自独立计数。"""
    p = _project(db)
    m1 = _model(db, name="X1"); m2 = _model(db, name="X2")
    _dev(db, p, m1, "点亮验收")
    _dev(db, p, m2, "订货")

    rows = dsvc.inventory_summary(db)
    by_name = {r["model_name"]: r for r in rows}
    assert by_name["X1"]["available"] == 1
    assert by_name["X2"]["pending"] == 1
