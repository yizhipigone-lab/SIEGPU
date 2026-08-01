"""还款确认测试：放款生成计划后逐期确认；重复确认拦截。"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.master import Supplier
from app.models.project import Project
from app.services import leasing_service as lsvc
from app.services import repayment_service as rsvc


def _process_with_plan(db):
    from app.models.user import User
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u); db.flush()
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush()
    sup = Supplier(name="金租A", type="资金供应商"); db.add(sup); db.flush()
    proc = lsvc.create_process(db, project_id=p.id, supplier_id=sup.id, total_amount=Decimal("4000000"),
                               annual_rate=Decimal("0.05"), term_periods=4, payment_freq="季",
                               repayment_method="等额本金", start_date=date(2026, 1, 1))
    proc.status = "已批"; db.flush()
    lsvc.disburse(db, process_id=proc.id, actual_disbursement_amount=Decimal("4000000"),
                  disbursement_date=date(2026, 2, 1), disbursed_by=u.id)
    return proc


def test_list_and_confirm_repayment(db):
    proc = _process_with_plan(db)
    reps = rsvc.list_repayments(db, proc.id)
    assert len(reps) == 4
    assert all(r.status == "待还" for r in reps)
    r1 = rsvc.confirm_repayment(db, repayment_id=reps[0].id,
                                actual_principal=reps[0].planned_principal,
                                actual_interest=reps[0].planned_interest, paid_date=date(2026, 5, 1))
    assert r1.status == "已还" and r1.paid_date == date(2026, 5, 1)


def test_double_confirm_blocked(db):
    proc = _process_with_plan(db)
    reps = rsvc.list_repayments(db, proc.id)
    rsvc.confirm_repayment(db, repayment_id=reps[0].id, actual_principal=Decimal("1"),
                           actual_interest=Decimal("0"), paid_date=date(2026, 5, 1))
    with pytest.raises(BusinessError):
        rsvc.confirm_repayment(db, repayment_id=reps[0].id, actual_principal=Decimal("1"),
                               actual_interest=Decimal("0"), paid_date=date(2026, 5, 1))
