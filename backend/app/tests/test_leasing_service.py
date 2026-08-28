"""金租流程服务集成测试。覆盖 9 节点生成、放款→流水+还款计划（Σ本金=放款额）、幂等、状态机。"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.capital import CapitalTransaction
from app.models.master import Supplier
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


def _lessor(db, name="金租A"):
    s = Supplier(name=name, type="资金供应商")
    db.add(s)
    db.flush()
    return s


def _full_process(db):
    u = _user(db)
    p = _project(db)
    l = _lessor(db)
    proc = svc.create_process(
        db, project_id=p.id, supplier_id=l.id, total_amount=Decimal("40000000"),
        annual_rate=Decimal("0.0435"), term_periods=20, payment_freq="季",
        repayment_method="等额本息", start_date=date(2026, 7, 1),
    )
    return u, p, proc


def test_create_process_generates_9_nodes(db):
    u, p, proc = _full_process(db)
    _, nodes, _proj, _sup = svc.get_process(db, proc.id)
    assert len(nodes) == 9
    assert [n.node_name for n in nodes] == [
        "接触", "业务交流", "资料提交", "金租审核", "一次上会", "二次上会", "访谈", "批方案", "放款",
    ]
    assert all(n.status == "未开始" for n in nodes)


def test_disburse_generates_txn_and_plan(db):
    u, p, proc = _full_process(db)
    proc.status = "已批"
    db.flush()
    proc2, txn, n = svc.disburse(
        db, process_id=proc.id, actual_disbursement_amount=Decimal("40000000"),
        disbursement_date=date(2026, 8, 10), disbursed_by=u.id,
    )
    assert n == 20
    assert proc2.status == "已放款"
    assert proc2.plan_generated is True
    # 1 条放款入金流水
    txns = db.execute(
        select(CapitalTransaction).where(CapitalTransaction.leasing_process_id == proc.id)
    ).scalars().all()
    assert len(txns) == 1
    assert txns[0].direction == "IN"
    assert txns[0].amount == Decimal("40000000")
    # 20 期还款，Σ计划本金 == 放款额（末期吸收尾差）
    reps = db.execute(
        select(Repayment).where(Repayment.leasing_process_id == proc.id).order_by(Repayment.period)
    ).scalars().all()
    assert len(reps) == 20
    assert sum(r.planned_principal for r in reps) == Decimal("40000000.00")
    assert reps[0].due_date == date(2026, 11, 10)  # 季度：放款日 +3 月


def test_double_disburse_blocked(db):
    u, p, proc = _full_process(db)
    proc.status = "已批"
    db.flush()
    svc.disburse(db, process_id=proc.id, actual_disbursement_amount=Decimal("40000000"),
                 disbursement_date=date(2026, 8, 10), disbursed_by=u.id)
    with pytest.raises(BusinessError):
        svc.disburse(db, process_id=proc.id, actual_disbursement_amount=Decimal("40000000"),
                     disbursement_date=date(2026, 8, 10), disbursed_by=u.id)


def test_disburse_missing_params_blocked(db):
    u = _user(db)
    p = _project(db)
    l = _lessor(db)
    proc = svc.create_process(db, project_id=p.id, supplier_id=l.id, total_amount=Decimal("1000000"))
    proc.status = "已批"
    db.flush()
    with pytest.raises(BusinessError):
        svc.disburse(db, process_id=proc.id, actual_disbursement_amount=Decimal("1000000"),
                     disbursement_date=date(2026, 2, 1), disbursed_by=u.id)


def test_create_rejects_non_lessor_supplier(db):
    p = _project(db)
    s = Supplier(name="设备商", type="设备供应商")
    db.add(s)
    db.flush()
    with pytest.raises(BusinessError):
        svc.create_process(db, project_id=p.id, supplier_id=s.id, total_amount=Decimal("1000"))


def test_node_illegal_transition_blocked(db):
    u, p, proc = _full_process(db)
    _, nodes, _proj, _sup = svc.get_process(db, proc.id)
    # 未开始 → 已完成 非法
    with pytest.raises(BusinessError):
        svc.advance_node(db, node_id=nodes[0].id, status="已完成")
    # 未开始 → 进行中 合法；进行中 → 已完成 合法
    svc.advance_node(db, node_id=nodes[0].id, status="进行中")
    svc.advance_node(db, node_id=nodes[0].id, status="已完成", actual_date=date(2026, 7, 5))


# ---- S12（缺陷#10）：金租申请编辑 / 作废 ----

def test_update_process_editable_before_disbursement(db):
    u, p, proc = _full_process(db)
    proc2 = svc.update_process(db, process_id=proc.id, total_amount=Decimal("50000000"),
                               annual_rate=Decimal("0.05"), notes="调整融资额")
    assert proc2.total_amount == Decimal("50000000")
    assert proc2.annual_rate == Decimal("0.05")
    # 非法字段被拒
    with pytest.raises(BusinessError):
        svc.update_process(db, process_id=proc.id, status="已批")


def test_void_process_and_guards(db):
    u, p, proc = _full_process(db)
    v = svc.void_process(db, process_id=proc.id)
    assert v.status == "已作废"
    # 已作废不可再作废 / 不可编辑
    with pytest.raises(BusinessError):
        svc.void_process(db, process_id=proc.id)
    with pytest.raises(BusinessError):
        svc.update_process(db, process_id=proc.id, total_amount=Decimal("1"))


def test_void_blocked_after_disbursement(db):
    u, p, proc = _full_process(db)
    proc.status = "已批"
    db.flush()
    svc.disburse(db, process_id=proc.id, actual_disbursement_amount=Decimal("40000000"),
                 disbursement_date=date(2026, 8, 1), disbursed_by=u.id)
    with pytest.raises(BusinessError):
        svc.void_process(db, process_id=proc.id)
