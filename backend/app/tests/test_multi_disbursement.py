"""金租分次放款：多笔、每笔关联具体采购验收、独立还款计划。"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.acceptance import AcceptanceRecord
from app.models.delivery import Order
from app.models.master import EquipmentModel, Supplier
from app.models.project import Project
from app.models.repayment import Repayment
from app.models.user import User
from app.services import leasing_service as svc


def _user(db):
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u)
    db.flush()
    return u


def _project(db, name="P"):
    p = Project(name=name, code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p)
    db.flush()
    return p


def _lessor(db):
    s = Supplier(name="金租A", type="资金供应商")
    db.add(s)
    db.flush()
    return s


def _acceptance(db, project_id):
    eq = EquipmentModel(name="测卡", category="大卡", gpu_type="A100")
    db.add(eq); db.flush()
    o = Order(project_id=project_id, equipment_model_id=eq.id, quantity=1,
              unit_price=Decimal("1"), total_amount=Decimal("1"))
    db.add(o); db.flush()
    a = AcceptanceRecord(project_id=project_id, acceptance_type="采购验收", order_id=o.id, status="已通过")
    db.add(a); db.flush()
    return a


def _proc(db, project_id, lessor_id):
    return svc.create_process(db, project_id=project_id, supplier_id=lessor_id,
                              total_amount=Decimal("40000000"), annual_rate=Decimal("0.04"),
                              term_periods=12, payment_freq="月", repayment_method="等额本息")


def test_add_disbursement_requires_valid_acceptance(db):
    u = _user(db)
    p = _project(db)
    l = _lessor(db)
    proc = _proc(db, p.id, l.id)
    with pytest.raises(BusinessError):
        svc.add_disbursement(db, process_id=proc.id, acceptance_id=uuid.uuid4(),
                             amount=Decimal("10000000"), disbursement_date=date(2026, 8, 1), created_by=u.id)


def test_add_disbursement_two_tranches_independent_plans(db):
    u = _user(db)
    p = _project(db)
    l = _lessor(db)
    proc = _proc(db, p.id, l.id)
    acc = _acceptance(db, p.id)

    d1, _, n1 = svc.add_disbursement(db, process_id=proc.id, acceptance_id=acc.id,
                                     amount=Decimal("10000000"), disbursement_date=date(2026, 8, 1), created_by=u.id)
    d2, _, n2 = svc.add_disbursement(db, process_id=proc.id, acceptance_id=acc.id,
                                     amount=Decimal("5000000"), disbursement_date=date(2026, 9, 1), created_by=u.id)

    assert n1 == 12 and n2 == 12
    rows = svc.list_disbursements(db, proc.id)
    assert len(rows) == 2
    assert {r.id for r in rows} == {d1.id, d2.id}
    assert all(r.acceptance_id == acc.id for r in rows)

    r1 = db.execute(select(Repayment).where(Repayment.disbursement_id == d1.id)).scalars().all()
    r2 = db.execute(select(Repayment).where(Repayment.disbursement_id == d2.id)).scalars().all()
    assert len(r1) == 12 and len(r2) == 12
    assert proc.status == "已放款"
