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


# ---------- 债①回归：纯核销（不经 /pay）写 paid_date ----------

def _receipt_txn(db, contract, amount, txn_date):
    """建一笔销售收款流水（IN），供核销用。"""
    from app.models.capital import CapitalTransaction
    txn = CapitalTransaction(project_id=contract.project_id, source_type="租金收入",
                             direction="IN", amount=amount, transaction_date=txn_date)
    db.add(txn)
    db.flush()
    return txn


def _user(db):
    """建一个真实用户，供 reconciled_by 等 FK→users 字段用（测试库空 schema 无 seed）。"""
    from app.models.user import User
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="核销员",
             password_hash="x", role="FINANCE_STAFF")
    db.add(u)
    db.flush()
    return u.id


def test_reconcile_full_sets_paid_date(db):
    """债①核心回归：纯核销（不调 mark_paid）全额匹配→同步写 paid_date（取流水到账日）。
    修复前：reconcile 只写 status=已核销，paid_date 留空→对账单 received 读 paid_date 漏计。"""
    c, o = _setup_lit_sales(db, contract_amount=Decimal("1000000"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("53333.33"),
                              issue_date=date(2026, 9, 30))  # 含税
    txn = _receipt_txn(db, c, Decimal("53333.33"), date(2026, 10, 20))
    isvc.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=_user(db))
    db.refresh(inv)
    assert inv.status == "已核销"
    assert inv.paid_date == date(2026, 10, 20)  # 取核销流水到账日
    # 三流对账 received 应反映（读 paid_date IS NOT NULL）——修复前为 0
    row = [r for r in isvc.reconciliation(db) if r["contract_id"] == str(c.id)][0]
    assert row["received"] == Decimal("53333.33")


def test_reconcile_partial_does_not_set_paid_date(db):
    """部分核销（流水未覆盖发票全额）不置 paid_date——发票尚未全额回款。"""
    c, o = _setup_lit_sales(db, contract_amount=Decimal("1000000"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("53333.33"),
                              issue_date=date(2026, 9, 30))
    txn = _receipt_txn(db, c, Decimal("20000.00"), date(2026, 10, 20))  # 不够覆盖
    isvc.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=_user(db))
    db.refresh(inv)
    assert inv.status != "已核销"  # 仍是「已开」
    assert inv.paid_date is None


def test_reconcile_does_not_overwrite_paid_date_from_pay(db):
    """已 /pay 置过 paid_date 的，核销不覆盖→守工作流 pay→reconcile 既有行为（零回归）。"""
    c, o = _setup_lit_sales(db, contract_amount=Decimal("1000000"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("53333.33"),
                              issue_date=date(2026, 9, 30))
    isvc.mark_paid(db, inv.id, date(2026, 10, 5))  # 先回款，paid_date=10/5
    txn = _receipt_txn(db, c, Decimal("53333.33"), date(2026, 10, 20))  # 到账日更晚
    isvc.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=_user(db))
    db.refresh(inv)
    assert inv.status == "已核销"
    assert inv.paid_date == date(2026, 10, 5)  # 仍是 /pay 的日期，未被流水日期覆盖


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


# ---------- S12（缺陷#19b）：发票空串日期容忍 ----------

def test_invoice_create_empty_string_dates(db):
    """缺陷#19b：前端不填日期提交空串不再 422（'' → None）。"""
    from app.schemas.invoice import InvoiceCreate
    m = InvoiceCreate(contract_id=uuid.uuid4(), amount=Decimal("100"), due_date="", issue_date="")
    assert m.due_date is None and m.issue_date is None
    m2 = InvoiceCreate(contract_id=uuid.uuid4(), amount=Decimal("100"), due_date="2026-08-01", issue_date=None)
    assert m2.due_date is not None and m2.issue_date is None
