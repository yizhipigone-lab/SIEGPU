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


# ---- S10（缺陷#11）：还款计划可调（planned_* 编辑 + 上限校验 + 已确认禁改） ----

def test_adjust_plan_changes_planned_values(db):
    """还款计划可按资金支付计划调整：改本金/利息/到期日。"""
    proc = _process_with_plan(db)
    reps = rsvc.list_repayments(db, proc.id)
    r = rsvc.adjust_plan(db, repayment_id=reps[0].id, planned_principal=Decimal("999000.00"),
                         planned_interest=Decimal("49999.99"), due_date=date(2026, 5, 15))
    assert r.planned_principal == Decimal("999000.00")
    assert r.planned_interest == Decimal("49999.99")
    assert r.due_date == date(2026, 5, 15)
    assert r.status == "待还"


def test_adjust_plan_total_cannot_exceed_disbursed(db):
    """缺陷#11 校验：Σ计划本金不得超放款总额（含多笔放款），超则拦。"""
    proc = _process_with_plan(db)  # 放款 400 万，4 期等额本金（每期 100 万）
    reps = rsvc.list_repayments(db, proc.id)
    # 第1期调到 999 万 → Σ 远超 400 万
    with pytest.raises(BusinessError) as exc:
        rsvc.adjust_plan(db, repayment_id=reps[0].id, planned_principal=Decimal("9990000"))
    assert "超" in str(exc.value.detail) or "放款" in str(exc.value.detail)
    # 未超时可调（400 万内挪移：1期压到 50 万，其余 3 期共 300 万）
    r = rsvc.adjust_plan(db, repayment_id=reps[0].id, planned_principal=Decimal("500000"))
    assert r.planned_principal == Decimal("500000")


def test_adjust_plan_blocked_after_confirmed(db):
    """已确认还款的期次不可改计划（防改历史）。"""
    proc = _process_with_plan(db)
    reps = rsvc.list_repayments(db, proc.id)
    rsvc.confirm_repayment(db, repayment_id=reps[0].id, actual_principal=Decimal("100"),
                           actual_interest=Decimal("0"), paid_date=date(2026, 5, 1))
    with pytest.raises(BusinessError):
        rsvc.adjust_plan(db, repayment_id=reps[0].id, planned_principal=Decimal("200"))
