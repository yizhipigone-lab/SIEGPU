"""资金池服务集成测试（连真实 PG 的 siegpu_test，每用例回滚）。覆盖审计 NF3/NF5 与设计书 §5.1/§5.2。"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BusinessError, InsufficientAllocatable
from app.models.project import Project
from app.models.user import User
from app.services import capital_service as svc


def _user(db):
    u = User(
        username=f"u{uuid.uuid4().hex[:6]}",
        display_name="t",
        password_hash="x",
        role="FINANCE_DIRECTOR",
        active=True,
    )
    db.add(u)
    db.flush()
    return u


def _project(db, name="P"):
    p = Project(name=name, code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p)
    db.flush()
    return p


def test_record_and_summary(db):
    u = _user(db)
    p = _project(db, "P1")
    svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                           direction="IN", amount=Decimal("1000000"), transaction_date=date(2026, 1, 1))
    svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                           direction="IN", amount=Decimal("2000000"), transaction_date=date(2026, 1, 2))
    svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                           direction="OUT", amount=Decimal("500000"), transaction_date=date(2026, 1, 3), category="付尾款")
    s = svc.pool_summary(db)
    assert s["total_in"] == Decimal("3000000")
    assert s["total_out"] == Decimal("500000")
    assert s["pool_balance"] == Decimal("2500000")
    assert s["per_project"][0]["net_position"] == Decimal("2500000")


def test_allocatable_after_partial_allocation(db):
    # NF5：注入 500 万，调出 300 万 → 可调 200 万（不能被锁成 0）
    u = _user(db)
    p1 = _project(db, "A")
    p2 = _project(db, "B")
    svc.record_transaction(db, created_by=u.id, project_id=p1.id, source_type="自有资金",
                           direction="IN", amount=Decimal("5000000"), transaction_date=date(2026, 1, 1))
    assert svc.project_allocatable(db, p1.id) == Decimal("5000000")
    svc.allocate(db, approved_by=u.id, from_project_id=p1.id, to_project_id=p2.id,
                 amount=Decimal("3000000"), allocation_date=date(2026, 1, 2), reason="B 付尾款")
    # 总余额不变（调配净 0）
    assert svc.pool_summary(db)["pool_balance"] == Decimal("5000000")
    assert svc.project_allocatable(db, p1.id) == Decimal("2000000")
    assert svc.project_allocatable(db, p2.id) == Decimal("3000000")


def test_allocate_insufficient(db):
    u = _user(db)
    p1 = _project(db, "A")
    p2 = _project(db, "B")
    with pytest.raises(InsufficientAllocatable):
        svc.allocate(db, approved_by=u.id, from_project_id=p1.id, to_project_id=p2.id,
                     amount=Decimal("100"), allocation_date=date(2026, 1, 1))


def test_allocate_same_project_rejected(db):
    u = _user(db)
    p1 = _project(db, "A")
    with pytest.raises(BusinessError):
        svc.allocate(db, approved_by=u.id, from_project_id=p1.id, to_project_id=p1.id,
                     amount=Decimal("100"), allocation_date=date(2026, 1, 1))


def test_record_bad_project(db):
    u = _user(db)
    with pytest.raises(BusinessError):
        svc.record_transaction(db, created_by=u.id, project_id=uuid.uuid4(), source_type="自有资金",
                               direction="IN", amount=Decimal("1"), transaction_date=date(2026, 1, 1))


def test_idempotency_key_unique(db):
    u = _user(db)
    p = _project(db, "P")
    svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                           direction="IN", amount=Decimal("100"), transaction_date=date(2026, 1, 1),
                           idempotency_key="k1")
    with pytest.raises(IntegrityError):
        svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                               direction="IN", amount=Decimal("100"), transaction_date=date(2026, 1, 1),
                               idempotency_key="k1")


def test_reverse_cancels_in_pool(db):
    u = _user(db)
    p = _project(db, "P")
    t = svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                               direction="IN", amount=Decimal("1000"), transaction_date=date(2026, 1, 1))
    assert svc.pool_summary(db)["pool_balance"] == Decimal("1000")
    svc.reverse_transaction(db, txn_id=t.id, reversed_by=u.id)
    # 反向记录方向相反、金额相等，SUM 自动抵消（NF3）
    assert svc.pool_summary(db)["pool_balance"] == Decimal("0")


def test_double_reverse_blocked(db):
    u = _user(db)
    p = _project(db, "P")
    t = svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                               direction="IN", amount=Decimal("1000"), transaction_date=date(2026, 1, 1))
    svc.reverse_transaction(db, txn_id=t.id, reversed_by=u.id)
    with pytest.raises(BusinessError):  # 已有红冲 → 409
        svc.reverse_transaction(db, txn_id=t.id, reversed_by=u.id)


def test_amount_must_be_positive(db):
    # DB CHECK amount > 0
    u = _user(db)
    p = _project(db, "P")
    with pytest.raises(IntegrityError):
        svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                               direction="IN", amount=Decimal("-1"), transaction_date=date(2026, 1, 1))
