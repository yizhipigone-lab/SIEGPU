"""进项税认证/抵扣测试（二期 W11-12，审计 A10）：认证→抵扣状态机 + 台账聚合 + audit 留痕。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.master import Customer, Supplier
from app.models.project import Project
from app.models.user import AuditLog
from app.services import contract_service as csvc
from app.services import invoice_service as isvc


def _purchase_invoice(db, amount=Decimal("1130"), p=None, c=None):
    if p is None:
        p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
        db.add(p); db.flush()
    if c is None:
        sup = Supplier(name=f"S-{uuid.uuid4().hex[:6]}", type="设备供应商")
        db.add(sup); db.flush()
        cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
        db.add(cust); db.flush()
        parent = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                                      amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
        c = csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                                 amount=Decimal("10000000"), tax_rate=Decimal("0.13"),
                                 parent_contract_id=parent.id)
    inv = isvc.create_invoice(db, contract_id=c.id, amount=amount,
                              invoice_no=f"INV-IN-{uuid.uuid4().hex[:6]}",
                              issue_date=date(2026, 8, 1))
    return p, inv


def test_certify_then_deduct(db):
    p, inv = _purchase_invoice(db)
    assert inv.certification_status is None
    isvc.certify_invoice(db, invoice_id=inv.id, certification_date=date(2026, 8, 12))
    assert inv.certification_status == "已认证" and inv.certification_date == date(2026, 8, 12)
    isvc.deduct_invoice(db, invoice_id=inv.id)
    assert inv.certification_status == "已抵扣"
    # audit 留痕
    logs = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "invoice", AuditLog.entity_id == inv.id,
        AuditLog.action == "UPDATE")).scalars().all()
    assert any(l.after_json.get("certification_status") == "已抵扣" for l in logs)


def test_certify_sales_invoice_rejected(db):
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("1130"),
                              issue_date=date(2026, 8, 1))
    with pytest.raises(BusinessError):  # 销售发票不参与进项
        isvc.certify_invoice(db, invoice_id=inv.id, certification_date=date(2026, 8, 12))


def test_deduct_before_certify_blocked(db):
    p, inv = _purchase_invoice(db)
    with pytest.raises(BusinessError):
        isvc.deduct_invoice(db, invoice_id=inv.id)
    isvc.certify_invoice(db, invoice_id=inv.id, certification_date=date(2026, 8, 12))
    with pytest.raises(BusinessError):  # 重复认证
        isvc.certify_invoice(db, invoice_id=inv.id, certification_date=date(2026, 8, 13))


def test_input_tax_ledger_aggregation(db):
    """台账：按认证状态聚合采购发票不含税/税额（1130 含税 13% → 不含税 1000 / 税 130）。"""
    p, inv1 = _purchase_invoice(db, Decimal("1130"))
    _, inv2 = _purchase_invoice(db, Decimal("2260"), p=p)
    isvc.certify_invoice(db, invoice_id=inv2.id, certification_date=date(2026, 8, 12))
    rows = isvc.input_tax_ledger(db, project_id=p.id)
    by_status = {r["certification_status"]: r for r in rows}
    assert by_status["未认证"]["count"] == 1
    assert by_status["未认证"]["amount_ex_tax"] == Decimal("1000.00")
    assert by_status["已认证"]["tax_amount"] == Decimal("260.00")  # 2260/1.13×0.13
