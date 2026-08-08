"""计费 + 发票/对账/超开 测试（§5.3/§5.6）。"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError, InvoiceOverContract
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Project
from app.services import billing_service as bsvc
from app.services import contract_service as csvc
from app.services import invoice_service as isvc
from app.services import order_service as osvc


def _setup_lit_sales(db, monthly_rent=Decimal("100000"), contract_amount=Decimal("1000000")):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush()
    cust = Customer(name="客户"); db.add(cust); db.flush()
    eq = EquipmentModel(name="H100", category="大卡"); db.add(eq); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=contract_amount, tax_rate=Decimal("0.13"), monthly_rent=monthly_rent)
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id, quantity=10, unit_price=Decimal("100000"))
    osvc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    return c, o


def test_billing_first_month_prorated(db):
    c, o = _setup_lit_sales(db)
    b1 = bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=1,
                               billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    # 月租 10 万，点亮 9/15，9 月 30 天剩 16 天 → 53333.33
    assert b1.amount == Decimal("53333.33")
    assert b1.days_in_period == 16
    assert b1.amount_ex_tax + b1.tax_amount == b1.amount


def test_billing_full_month_period2(db):
    c, o = _setup_lit_sales(db)
    b2 = bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=2,
                               billing_date=date(2026, 10, 31), created_by=uuid.uuid4())
    assert b2.amount == Decimal("100000.00")
    assert b2.days_in_period == 31


def test_billing_dup_period_blocked(db):
    c, o = _setup_lit_sales(db)
    from app.core.exceptions import BusinessError
    bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=1,
                          billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
    with pytest.raises(BusinessError, match="已计费"):  # v3.1: service层去重
        bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=1,
                              billing_date=date(2026, 9, 30), created_by=uuid.uuid4())


def test_invoice_over_contract_blocked(db):
    c, o = _setup_lit_sales(db, contract_amount=Decimal("1000"))  # 合同不含税 1000
    # 第一张：含税 1000 → 不含税 884.96，未超
    isvc.create_invoice(db, contract_id=c.id, amount=Decimal("1000"))
    # 第二张：含税 500 → 不含税 442.48；累计 1327 > 1000×1.001 → 超开
    with pytest.raises(InvoiceOverContract):
        isvc.create_invoice(db, contract_id=c.id, amount=Decimal("500"))


def test_reconciliation_gaps(db):
    c, o = _setup_lit_sales(db, contract_amount=Decimal("1000000"))
    bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=1,
                          billing_date=date(2026, 9, 30), created_by=uuid.uuid4())  # 53333.33 含税
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("53333.33"), issue_date=date(2026, 9, 30))
    rows = isvc.reconciliation(db)
    row = [r for r in rows if r["contract_id"] == str(c.id)][0]
    # billed 不含税 = 53333.33/1.13 ≈ 47197.64
    assert row["billed"] == Decimal("47197.64")
    assert row["invoiced"] == Decimal("47197.64")
    assert row["gap_billed"] == Decimal("1000000.00") - Decimal("47197.64")
    # 未付款 → received = 0
    assert row["received"] == Decimal("0.00")
    # 标记收款后 received 含税 = 53333.33
    isvc.mark_paid(db, inv.id, date(2026, 10, 15))
    rows2 = isvc.reconciliation(db)
    row2 = [r for r in rows2 if r["contract_id"] == str(c.id)][0]
    assert row2["received"] == Decimal("53333.33")


# ---------- 一期 W3-4：设备粒度订单禁走旧 generate_billing ----------

def test_generate_billing_blocked_for_device_order(db):
    from app.services import device_service as dsvc
    c, o = _setup_lit_sales(db)  # 普通订单已点亮（合法旧路径）
    # 挂设备→变 device 路径，旧 order 维度计费应被防双计闸拒绝
    d = dsvc.create_device(db, project_id=o.project_id, equipment_model_id=o.equipment_model_id)
    dsvc.add_to_batch(db, device_id=d.id, batch_id=o.id)
    with pytest.raises(BusinessError):
        bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=1,
                              billing_date=date(2026, 9, 30), created_by=uuid.uuid4())
