"""一期 W5-6 测试（Phase B）：按台计费（device 维度）。

generate_billing_device：
- 金额取 device.monthly_price（**不读** contract.monthly_rent），首月按点亮验收剩余天数比例；
- device 维 dup-check（service）+ DB 部分唯一索引 uq_billing_period(device_id, period_index) 兜底；
- sales_order_id 经 device.sales_contract_id→SalesOrder.contract_id 反查 thread（D3）。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BusinessError
from app.models.billing import Billing
from app.models.project import Contract, Project
from app.models.sales_order import SalesOrder
from app.models.master import EquipmentModel
from app.services import billing_service as bsvc
from app.services import device_service as dsvc


def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8); db.add(e); db.flush(); return e


def _sales_contract(db, p, monthly_rent=Decimal("999999")):
    """销售合同；monthly_rent 默认设极大值以证明按台计费**不读**它。"""
    c = Contract(project_id=p.id, type="SALES", party_type="customer", party_id=uuid.uuid4(),
                 direction="RECEIVABLE", amount=Decimal("1000000"),
                 tax_rate=Decimal("0.13"), monthly_rent=monthly_rent)
    db.add(c); db.flush(); return c


def _advance_through(db, device_id, target_stage, actual_date=date(2026, 9, 15)):
    for st in dsvc.DEVICE_STAGES[:dsvc.DEVICE_STAGES.index(target_stage) + 1]:
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="进行中")
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="已完成",
                                  actual_date=actual_date)


def _lit_device(db, p=None, e=None, monthly_price=Decimal("10000"),
                light_on=date(2026, 9, 15), sales_contract_id=None):
    """建一台表内自有设备（带 monthly_price + purchase_value）并推进到点亮验收已完成。"""
    p = p or _project(db); e = e or _equipment(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id, ownership="表内自有",
                           purchase_value=Decimal("960000"), monthly_price=monthly_price,
                           sales_contract_id=sales_contract_id)
    _advance_through(db, d.id, "点亮验收", actual_date=light_on)
    return d


# ---------- 金额取 device.monthly_price（D2 核心） ----------

def test_device_billing_first_month_prorated_from_monthly_price(db):
    """period1：monthly_price=10000、点亮 9/15（9 月 30 天剩 16 天）→ 5333.33。

    contract.monthly_rent 故意设 999999，金额仍为 10000×16/30 → 证明取 device.monthly_price。
    """
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)  # monthly_rent=999999
    d = _lit_device(db, p, e, monthly_price=Decimal("10000"), light_on=date(2026, 9, 15))

    b = bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert b.amount == Decimal("5333.33")
    assert b.days_in_period == 16
    assert b.amount_ex_tax + b.tax_amount == b.amount
    assert b.device_id == d.id


def test_device_billing_full_month_period2(db):
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d = _lit_device(db, p, e, monthly_price=Decimal("10000"))
    b = bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=2,
                                     billing_date=date(2026, 10, 31), created_by=uuid.uuid4())
    assert b.amount == Decimal("10000.00")
    assert b.days_in_period == 31


# ---------- 缺值守卫 ----------

def test_device_billing_without_monthly_price_raises(db):
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d = _lit_device(db, p, e, monthly_price=None)
    with pytest.raises(BusinessError) as exc:
        bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert exc.value.detail["code"] == "BAD_REQUEST"


def test_device_billing_not_lit_raises(db):
    """设备仅到上架（未点亮验收）→ 计费起点缺失抛 BAD_REQUEST。"""
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id, ownership="表内自有",
                           purchase_value=Decimal("960000"), monthly_price=Decimal("10000"))
    _advance_through(db, d.id, "上架")  # 未推进到点亮验收
    with pytest.raises(BusinessError) as exc:
        bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert exc.value.detail["code"] == "BAD_REQUEST"


def test_device_billing_contract_not_sales_raises(db):
    from app.models.project import Contract
    p = _project(db); e = _equipment(db)
    pc = Contract(project_id=p.id, type="PURCHASE", party_type="supplier", party_id=uuid.uuid4(),
                  direction="PAYABLE", amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    db.add(pc); db.flush()
    d = _lit_device(db, p, e, monthly_price=Decimal("10000"))
    with pytest.raises(BusinessError) as exc:
        bsvc.generate_billing_device(db, device_id=d.id, contract_id=pc.id, period_index=1,
                                     billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert exc.value.detail["code"] == "BAD_REQUEST"


# ---------- 重复计费阻断（service + DB 唯一索引双路径） ----------

def test_device_billing_dup_period_blocked_service(db):
    """service 层 dup-check：同期二次调用 → DUPLICATE 409。"""
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d = _lit_device(db, p, e, monthly_price=Decimal("10000"))
    bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                 billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    with pytest.raises(BusinessError) as exc:
        bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert exc.value.detail["code"] == "DUPLICATE"


def test_device_billing_dup_period_blocked_unique_index(db):
    """DB 部分唯一索引兜底：绕过 service 直接插同期 device billing → IntegrityError。"""
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d = _lit_device(db, p, e, monthly_price=Decimal("10000"))
    bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                 billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    # 绕过 service dup-check，直接构造同期 Billing
    dup = Billing(project_id=p.id, contract_id=c.id, order_id=None, device_id=d.id,
                  period_index=1, period_label="2026-09", billing_date=date(2026, 9, 30),
                  days_in_period=16, amount=Decimal("1.00"), amount_ex_tax=Decimal("0.88"),
                  tax_amount=Decimal("0.12"), tax_rate=Decimal("0.13"))
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.flush()


# ---------- sales_order_id thread（D3） ----------

def test_device_billing_threads_sales_order_id_via_contract(db):
    """device.sales_contract_id → SalesOrder.contract_id 命中 → billing.sales_order_id 透传。"""
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    so = SalesOrder(project_id=p.id, contract_id=c.id, equipment_model_id=e.id, quantity=8,
                    monthly_rent_per_unit=Decimal("10000"), total_monthly_rent=Decimal("80000"))
    db.add(so); db.flush()
    d = _lit_device(db, p, e, monthly_price=Decimal("10000"), sales_contract_id=c.id)

    b = bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert b.sales_order_id == so.id


def test_device_billing_no_sales_order_when_contract_unlinked(db):
    """device 无 sales_contract_id → sales_order_id=None；billings 仍成立（order/sales_order 均可空）。"""
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d = _lit_device(db, p, e, monthly_price=Decimal("10000"))  # sales_contract_id=None
    b = bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert b.sales_order_id is None
    assert b.order_id is None  # 导入设备无订单


# ---------- list 过滤 + 双轨回归 ----------

def test_list_billings_filter_by_device(db):
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d1 = _lit_device(db, p, e, monthly_price=Decimal("10000"))
    d2 = _lit_device(db, p, e, monthly_price=Decimal("10000"))
    bsvc.generate_billing_device(db, device_id=d1.id, contract_id=c.id, period_index=1,
                                 billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    bsvc.generate_billing_device(db, device_id=d2.id, contract_id=c.id, period_index=1,
                                 billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    rows = bsvc.list_billings(db, device_id=d1.id)
    assert len(rows) == 1 and rows[0].device_id == d1.id


def test_legacy_generate_billing_regression(db):
    """双轨回归：legacy order 维 generate_billing 仍走 contract.monthly_rent（不受 W5-6 影响）。"""
    from app.services import contract_service as csvc
    from app.services import order_service as osvc
    from app.models.master import Customer
    cust = Customer(name="客户"); db.add(cust); db.flush()
    p = _project(db); e = _equipment(db)
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=Decimal("1000000"), tax_rate=Decimal("0.13"),
                             monthly_rent=Decimal("100000"))
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=e.id,
                          quantity=10, unit_price=Decimal("100000"))
    osvc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    b = bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=1,
                              billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    assert b.amount == Decimal("53333.33")  # 100000 × 16/30，来自 contract.monthly_rent
    assert b.device_id is None  # legacy 路径 device_id 为空


def test_light_rework_blocked_when_device_billing_only_off_balance(db):
    """D5 has_billing-only 分支（W5-6 审计补测）：金租表外设备点亮验收不建 Asset（has_asset=False），
    但被按台计费后 has_billing=True → 点亮验收 已完成→不合格 仍被 STATE_ERROR 拦。

    隔离 test_device.py::test_light_rework_blocked_when_on_balance_asset_exists（has_asset 分支）
    未覆盖的 OR 另一半——证明 has_billing 单独为真也能触发守门，而非仅靠 has_asset。
    """
    from sqlalchemy import select
    from app.models.asset import Asset
    p = _project(db); e = _equipment(db)
    c = _sales_contract(db, p)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           ownership="金租表外", leasing_mode="直租",
                           purchase_value=Decimal("960000"), monthly_price=Decimal("10000"))
    _advance_through(db, d.id, "点亮验收", actual_date=date(2026, 9, 15))
    # 金租表外点亮：上架建 off_balance_register、点亮不建 Asset → has_asset=False（隔离前提）
    assert db.execute(select(Asset).where(Asset.device_id == d.id)).scalar_one_or_none() is None
    bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                 billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    with pytest.raises(BusinessError) as exc:
        dsvc.advance_device_stage(db, device_id=d.id, stage="点亮验收", status="不合格")
    assert exc.value.detail["code"] == "STATE_ERROR"
