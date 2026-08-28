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


# ---------------- 四期 W4：资金池分池 ----------------

def test_bank_loan_and_repay(db):
    """记银行借款→银行池↑；还银行→银行池↓；超额还银行被拦。"""
    u = _user(db); p = _project(db)
    svc.record_bank_loan(db, project_id=p.id, amount=Decimal("5000000"),
                         transaction_date=date(2026, 1, 1), created_by=u.id)
    assert svc.pool_balance(db, p.id, "BANK") == Decimal("5000000")
    svc.repay_bank(db, project_id=p.id, amount=Decimal("2000000"),
                   transaction_date=date(2026, 2, 1), created_by=u.id)
    assert svc.pool_balance(db, p.id, "BANK") == Decimal("3000000")
    # 超额还银行 → 拦
    with pytest.raises(BusinessError):
        svc.repay_bank(db, project_id=p.id, amount=Decimal("99999999"),
                       transaction_date=date(2026, 3, 1), created_by=u.id)


def test_prepayment_pool_flow(db):
    """预付(银行池出钱)→挂账池↑；退回→挂账池↓+现金回池↑；核销→挂账池↓。余额不足拦截。"""
    u = _user(db); p = _project(db)
    svc.record_bank_loan(db, project_id=p.id, amount=Decimal("1000000"),
                         transaction_date=date(2026, 1, 1), created_by=u.id)
    # S3（缺陷#9）：预付必带供应商与采购合同
    from app.models.master import Supplier
    from app.models.project import Contract
    sup = Supplier(name="供应商A", type="设备供应商")
    db.add(sup); db.flush()
    con = Contract(project_id=p.id, type="PURCHASE", party_type="supplier", party_id=sup.id,
                   direction="PAYABLE", amount=Decimal("500000"), contract_no="CG-P")
    db.add(con); db.flush()
    # 预付 40 万：银行池 100→60，挂账池 0→40
    svc.record_prepayment(db, project_id=p.id, amount=Decimal("400000"),
                          transaction_date=date(2026, 1, 5), created_by=u.id, from_pool="BANK",
                          supplier_id=sup.id, contract_id=con.id)
    assert svc.pool_balance(db, p.id, "BANK") == Decimal("600000")
    assert svc.pool_balance(db, p.id, "PREPAY") == Decimal("400000")
    # 供应商退回 15 万（金租放款后）：挂账池 40→25，银行池 60→75
    svc.refund_prepayment(db, project_id=p.id, amount=Decimal("150000"),
                          transaction_date=date(2026, 2, 1), created_by=u.id, to_pool="BANK")
    assert svc.pool_balance(db, p.id, "PREPAY") == Decimal("250000")
    assert svc.pool_balance(db, p.id, "BANK") == Decimal("750000")
    # 拿发票核销 20 万：挂账池 25→5（不涉现金）
    svc.offset_prepayment(db, project_id=p.id, amount=Decimal("200000"),
                          transaction_date=date(2026, 2, 10), created_by=u.id)
    assert svc.pool_balance(db, p.id, "PREPAY") == Decimal("50000")
    assert svc.pool_balance(db, p.id, "BANK") == Decimal("750000")  # 核销不动现金池
    # 挂账余额不足核销 → 拦
    with pytest.raises(BusinessError):
        svc.offset_prepayment(db, project_id=p.id, amount=Decimal("999999"),
                              transaction_date=date(2026, 3, 1), created_by=u.id)


def test_prepay_from_pool_cannot_be_prepay(db):
    """预付不能从预付款池支出（防呆）。"""
    u = _user(db); p = _project(db)
    with pytest.raises(BusinessError):
        svc.record_prepayment(db, project_id=p.id, amount=Decimal("1"),
                              transaction_date=date(2026, 1, 1), created_by=u.id, from_pool="PREPAY")


def test_pools_by_project_and_summary(db):
    """pools_by_project 返回 4 池；pool_summary.by_pool 含 4 池 net。"""
    u = _user(db); p = _project(db)
    svc.record_bank_loan(db, project_id=p.id, amount=Decimal("1000000"),
                         transaction_date=date(2026, 1, 1), created_by=u.id)
    from app.models.master import Supplier
    from app.models.project import Contract
    sup = Supplier(name="供应商A", type="设备供应商")
    db.add(sup); db.flush()
    con = Contract(project_id=p.id, type="PURCHASE", party_type="supplier", party_id=sup.id,
                   direction="PAYABLE", amount=Decimal("500000"), contract_no="CG-P")
    db.add(con); db.flush()
    svc.record_prepayment(db, project_id=p.id, amount=Decimal("300000"),
                          transaction_date=date(2026, 1, 2), created_by=u.id, from_pool="BANK",
                          supplier_id=sup.id, contract_id=con.id)
    pools = svc.pools_by_project(db, p.id)
    assert pools["BANK"] == Decimal("700000")
    assert pools["PREPAY"] == Decimal("300000")
    assert pools["LEASING"] == Decimal("0")
    s = svc.pool_summary(db)
    assert s["by_pool"]["BANK"]["net"] == Decimal("700000")
    assert s["by_pool"]["PREPAY"]["net"] == Decimal("300000")


def test_prepayment_creates_ledger_row(db):
    """S3 缺陷#6/#9：手工预付同事务落台账行（含日期/供应商/采购合同，与流水共享幂等前缀）。"""
    from sqlalchemy import select
    from app.models.master import Supplier
    from app.models.prepayment import Prepayment
    from app.models.project import Contract
    u = _user(db); p = _project(db)
    svc.record_bank_loan(db, project_id=p.id, amount=Decimal("1000000"),
                         transaction_date=date(2026, 1, 1), created_by=u.id)
    sup = Supplier(name="供应商A", type="设备供应商")
    db.add(sup); db.flush()
    con = Contract(project_id=p.id, type="PURCHASE", party_type="supplier", party_id=sup.id,
                   direction="PAYABLE", amount=Decimal("500000"), contract_no="CG-P")
    db.add(con); db.flush()
    svc.record_prepayment(db, project_id=p.id, amount=Decimal("400000"),
                          transaction_date=date(2026, 1, 5), created_by=u.id, from_pool="BANK",
                          supplier_id=sup.id, contract_id=con.id)
    row = db.execute(select(Prepayment).where(Prepayment.deleted_at.is_(None))).scalars().first()
    assert row is not None
    assert row.payment_date == date(2026, 1, 5)
    assert row.supplier_id == sup.id
    assert row.contract_id == con.id
    assert row.amount == Decimal("400000")
    assert row.settled_amount == Decimal("0")
    # 幂等键与流水共享前缀（与 /capital/prepayment 双流水一致）
    assert row.idempotency_key.startswith("prepay:") and row.idempotency_key.endswith(":ledger")


def test_leasing_disburse_lands_in_leasing_pool(db):
    """金租放款流水入金租池（pool=LEASING）。"""
    from datetime import date as _date
    from app.models.leasing import LeasingProcess
    from app.models.master import Supplier
    from app.services import leasing_service as lsvc
    u = _user(db); p = _project(db)
    sup = Supplier(name="金租A", type="资金供应商"); db.add(sup); db.flush()
    proc = lsvc.create_process(db, project_id=p.id, supplier_id=sup.id, total_amount=Decimal("1000000"),
                               annual_rate=Decimal("0.05"), term_periods=3, payment_freq="月",
                               repayment_method="等额本息")
    lsvc.disburse(db, process_id=proc.id, actual_disbursement_amount=Decimal("1000000"),
                  disbursement_date=_date(2026, 1, 1), disbursed_by=u.id)
    assert svc.pool_balance(db, p.id, "LEASING") == Decimal("1000000")


def test_reverse_stays_in_same_pool(db):
    """红冲同池反向：银行池红冲后余额抵消。"""
    u = _user(db); p = _project(db)
    t = svc.record_bank_loan(db, project_id=p.id, amount=Decimal("1000"),
                             transaction_date=date(2026, 1, 1), created_by=u.id)
    assert svc.pool_balance(db, p.id, "BANK") == Decimal("1000")
    svc.reverse_transaction(db, txn_id=t.id, reversed_by=u.id)
    assert svc.pool_balance(db, p.id, "BANK") == Decimal("0")


# ---- S11（缺陷#23）：银行授信使用情况 ----

def test_bank_credit_usage_and_limit(db):
    """已用授信 = 借款 − 偿还；超额借款被拦（银行授信不足）。"""
    from app.models.master import Bank
    u = _user(db); p = _project(db)
    bank = Bank(name="工行", credit_line=Decimal("5000000"), annual_rate=Decimal("0.04"))
    db.add(bank); db.flush()
    svc.record_bank_loan(db, project_id=p.id, amount=Decimal("3000000"),
                         transaction_date=date(2026, 1, 1), created_by=u.id, bank_id=bank.id)
    assert svc.bank_credit_usage(db)[str(bank.id)] == Decimal("3000000")
    # 还 100 万 → 已用 200 万
    svc.repay_bank(db, project_id=p.id, amount=Decimal("1000000"),
                   transaction_date=date(2026, 2, 1), created_by=u.id, bank_id=bank.id)
    assert svc.bank_credit_usage(db)[str(bank.id)] == Decimal("2000000")
    # 恰好等于剩余 → 允许；超出 → 拦
    svc.assert_bank_credit_available(db, bank.id, Decimal("3000000"))
    with pytest.raises(BusinessError) as exc:
        svc.assert_bank_credit_available(db, bank.id, Decimal("4000000"))
    assert "授信" in str(exc.value.detail)


def test_replacement_backfills_bank_id(db):
    """K6：置换归还流水回填原付款 bank_id → 授信已用正确抵减。"""
    from app.models.master import Bank, Supplier
    from app.services import funding_service as fs
    from app.services import leasing_service as lsvc
    u = _user(db); p = _project(db)
    bank = Bank(name="工行", credit_line=Decimal("5000000"), annual_rate=Decimal("0.04"))
    db.add(bank); db.flush()
    svc.record_bank_loan(db, project_id=p.id, amount=Decimal("3000000"),
                         transaction_date=date(2026, 1, 1), created_by=u.id, bank_id=bank.id)
    # 垫资付款（银行流贷 OUT，带 bank_id）
    svc.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                           direction="OUT", amount=Decimal("1000000"),
                           transaction_date=date(2026, 1, 15), bank_id=bank.id)
    assert svc.bank_credit_usage(db)[str(bank.id)] == Decimal("3000000")  # 垫资不改已用
    # 金租放款置换 100 万 → 归还流贷 IN 回填 bank_id → 已用 200 万
    sup = Supplier(name="金租A", type="资金供应商")
    db.add(sup); db.flush()
    proc = lsvc.create_process(db, project_id=p.id, supplier_id=sup.id, total_amount=Decimal("1000000"),
                               annual_rate=Decimal("0.05"), term_periods=3, payment_freq="月",
                               repayment_method="等额本息")
    fs.execute_replacement(db, project_id=p.id, leasing_process_id=proc.id,
                           disbursement_amount=Decimal("1000000"), disbursement_date=date(2026, 2, 1),
                           created_by=u.id)
    assert svc.bank_credit_usage(db)[str(bank.id)] == Decimal("2000000")
