"""资金置换引擎单元测试。"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.capital import CapitalTransaction
from app.models.funding import FundingReplacement
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.project import Project
from app.services import capital_service as cap
from app.services import funding_service as fund

D = Decimal


@pytest.fixture
def project_id(db):
    """准备：项目 + 银行流贷OUT + 自有资金OUT（未置换）。"""
    cust = Customer(name="测客", industry="测试")
    db.add(cust); db.flush()
    p = Project(name="置换测试项目", code="TEST-REPLACE", total_investment=D("1000000"))
    db.add(p); db.flush()
    pid = p.id
    # 银行流贷付款 70万
    t1 = CapitalTransaction(project_id=pid, source_type="银行流贷", direction="OUT",
        amount=D("700000"), transaction_date=date(2026, 1, 10), category="付设备款")
    db.add(t1)
    # 自有资金付款 30万
    t2 = CapitalTransaction(project_id=pid, source_type="自有资金", direction="OUT",
        amount=D("300000"), transaction_date=date(2026, 1, 10), category="付设备款")
    db.add(t2)
    db.flush()
    return pid


def test_full_replacement(db, project_id):
    """全额置换：放款100万覆盖全部付款。"""
    replacements = fund.execute_replacement(
        db, project_id=project_id, leasing_process_id=None,
        disbursement_amount=D("1000000"), disbursement_date=date(2026, 4, 10),
        created_by=None,
    )
    db.flush()

    assert len(replacements) == 2
    assert replacements[0].amount == D("700000")
    assert replacements[0].source_type_replaced == "银行流贷"
    assert replacements[1].amount == D("300000")
    assert replacements[1].source_type_replaced == "自有资金"

    # 原付款应为已全额置换
    txn1 = db.get(CapitalTransaction, replacements[0].original_txn_id)
    assert txn1.is_replaced is True
    assert txn1.replaced_amount == txn1.amount

    txn2 = db.get(CapitalTransaction, replacements[1].original_txn_id)
    assert txn2.is_replaced is True


def test_partial_replacement(db, project_id):
    """部分置换：放款50万只够还流贷的一部分。"""
    replacements = fund.execute_replacement(
        db, project_id=project_id, leasing_process_id=None,
        disbursement_amount=D("500000"), disbursement_date=date(2026, 4, 10),
        created_by=None,
    )
    db.flush()

    assert len(replacements) == 1
    assert replacements[0].amount == D("500000")
    assert replacements[0].source_type_replaced == "银行流贷"

    txn = db.get(CapitalTransaction, replacements[0].original_txn_id)
    assert txn.is_replaced is False  # 部分置换
    assert txn.replaced_amount == D("500000")


def test_no_eligible_txns(db):
    """无待置换付款时不报错。"""
    replacements = fund.execute_replacement(
        db, project_id=None, leasing_process_id=None,
        disbursement_amount=D("100000"), disbursement_date=date(2026, 4, 10),
        created_by=None,
    )
    assert replacements == []


def test_zero_disbursement(db):
    """放款额为零直接返回空。"""
    replacements = fund.execute_replacement(
        db, project_id=None, leasing_process_id=None,
        disbursement_amount=D("0"), disbursement_date=date(2026, 4, 10),
        created_by=None,
    )
    assert replacements == []


def test_list_replacements(db, project_id):
    """查询置换记录。"""
    fund.execute_replacement(db, project_id=project_id, leasing_process_id=None,
        disbursement_amount=D("1000000"), disbursement_date=date(2026, 4, 10),
        created_by=None)
    db.flush()

    result = fund.list_replacements(db, project_id=project_id)
    assert len(result) == 2
