"""S8（缺陷#12/#13）：直付双流水（负债入账+付款OUT）、入池单流水、置换归还日可指定。"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.acceptance import AcceptanceRecord
from app.models.delivery import Order
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Contract, Project
from app.services import acceptance_service as asvc
from app.services import capital_service as csvc
from app.services import leasing_service as lsvc


def _mk(db):
    """项目 + 采购合同/订单 + 已通过采购验收 + 已批金租申请。返回 (project, acceptance, process, pc)。"""
    from app.models.user import User
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u); db.flush()
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    sup = Supplier(name="设备供应商", type="设备供应商")
    db.add(sup); db.flush()
    eq = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(eq); db.flush()
    sc = Contract(project_id=p.id, type="SALES", party_type="customer", party_id=cust.id,
                  direction="RECEIVABLE", amount=Decimal("1000000"))
    db.add(sc); db.flush()
    pc = Contract(project_id=p.id, type="PURCHASE", party_type="supplier", party_id=sup.id,
                  direction="PAYABLE", amount=Decimal("500000"), contract_no="CG-T")
    db.add(pc); db.flush()
    o = Order(project_id=p.id, equipment_model_id=eq.id, quantity=1,
              unit_price=Decimal("500000"), total_amount=Decimal("500000"), contract_id=pc.id)
    db.add(o); db.flush()
    ar = asvc.create_acceptance(db, project_id=p.id, acceptance_type="采购验收",
                                order_id=o.id, quantity_accepted=1)
    ar = asvc.approve_acceptance(db, ar)
    db.flush()
    sup2 = Supplier(name="金租A", type="资金供应商")
    db.add(sup2); db.flush()
    proc = lsvc.create_process(db, project_id=p.id, supplier_id=sup2.id, total_amount=Decimal("400000"),
                               annual_rate=Decimal("0.05"), term_periods=3, payment_freq="月",
                               repayment_method="等额本息")
    proc.status = "已批"
    db.flush()
    return p, ar, proc, pc


def _txns(db, process_id):
    from sqlalchemy import select
    from app.models.capital import CapitalTransaction
    return db.execute(
        select(CapitalTransaction).where(CapitalTransaction.leasing_process_id == process_id)
    ).scalars().all()


def test_pool_mode_single_inflow(db):
    """缺陷#12：入池模式 = 单笔金租融资 IN 入金租池（现状语义）。"""
    p, ar, proc, pc = _mk(db)
    d, txn, n = lsvc.add_disbursement(db, process_id=proc.id, acceptance_id=ar.id,
                                      amount=Decimal("400000"), disbursement_date=date(2026, 3, 1),
                                      mode="入池", created_by=None)
    assert d.mode == "入池"
    txns = _txns(db, proc.id)
    assert len(txns) == 1 and txns[0].direction == "IN" and txns[0].pool == "LEASING"
    assert txns[0].category == "放款"
    assert csvc.pool_balance(db, p.id, "LEASING") == Decimal("400000")
    assert n == 3  # 还款计划照常


def test_direct_mode_dual_flows(db):
    """缺陷#12：直付 = 负债入账 IN + 供应商付款 OUT 两笔（LEASING 池恒 0，无现金进池）。"""
    p, ar, proc, pc = _mk(db)
    d, txn, n = lsvc.add_disbursement(db, process_id=proc.id, acceptance_id=ar.id,
                                      amount=Decimal("400000"), disbursement_date=date(2026, 3, 1),
                                      mode="直付", created_by=None)
    assert d.mode == "直付"
    txns = _txns(db, proc.id)
    assert len(txns) == 2
    cats = {t.category for t in txns}
    assert cats == {"直付融资入账", "金租直付货款"}
    # K5：采购验收 → 订单 → 采购合同，contract_id 落在两笔流水上
    assert all(t.contract_id == pc.id for t in txns)
    # 同池对冲 → LEASING 池余额 0（直付=金租代付，现金不经赛意）
    assert csvc.pool_balance(db, p.id, "LEASING") == Decimal("0")
    assert n == 3


def test_replacement_date_not_hardcoded(db):
    """缺陷#13：置换归还日可指定（不再写死放款日）；缺省=放款日。"""
    from app.models.master import Bank
    from app.services import funding_service as fs
    p, ar, proc, pc = _mk(db)
    bank = Bank(name="工行", credit_line=Decimal("10000000"), annual_rate=Decimal("0.04"))
    db.add(bank); db.flush()
    csvc.record_bank_loan(db, project_id=p.id, amount=Decimal("500000"),
                          transaction_date=date(2026, 1, 10), created_by=None, bank_id=bank.id)
    # 垫资付款（银行流贷 OUT，待置换）
    csvc.record_transaction(db, created_by=None, project_id=p.id, source_type="银行流贷",
                            direction="OUT", amount=Decimal("300000"),
                            transaction_date=date(2026, 2, 1), bank_id=bank.id)
    # 放款日 2026-03-01，指定置换归还日 2026-03-15
    lsvc.add_disbursement(db, process_id=proc.id, acceptance_id=ar.id, amount=Decimal("400000"),
                          disbursement_date=date(2026, 3, 1), mode="入池",
                          replacement_date=date(2026, 3, 15), created_by=None)
    reps = [r for r in _txns(db, proc.id) if r.category == "置换归还"]
    assert len(reps) == 1
    assert reps[0].transaction_date == date(2026, 3, 15)  # 不再写死放款日
    assert reps[0].bank_id == bank.id  # K6 回填
