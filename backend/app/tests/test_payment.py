"""付款三重管控 + 多对多核销测试（二期 W11-12）。

覆盖：申请（预付款冲抵校验）→ 审批 → 登记（现金=申请−冲抵，冲抵 FIFO 抵扣 devices 单源）
→ 核销多对多 golden（一笔付多发票 / 多笔核销同一发票 / 待认领 / 方向校验 / 超额拦截）
→ 外币核销汇兑损益按设备价值占比分摊至设备（与 W5-6 compute_exchange_diff 同口径）。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.billing import Invoice
from app.models.capital import CapitalTransaction
from app.models.device import Device
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.payment import PaymentSettlement
from app.models.project import Project
from app.services import approval_service, capital_service
from app.services import contract_service as csvc
from app.services import device_service as dsvc
from app.services import invoice_service as isvc
from app.services import payment_service as svc


def _project(db) -> Project:
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def _purchase_contract(db, p, currency=None):
    sup = Supplier(name=f"S-{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add(sup); db.flush()
    return csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                                amount=Decimal("10000000"), tax_rate=Decimal("0.13"),
                                currency_code=currency)


def _invoice(db, c, amount, currency=None, rate=None) -> Invoice:
    return isvc.create_invoice(db, contract_id=c.id, amount=amount,
                               invoice_no=f"INV-P-{uuid.uuid4().hex[:6]}",
                               issue_date=date(2026, 8, 1), currency_code=currency,
                               invoice_rate=rate)


def _txn(db, p, amount, direction="OUT", currency=None, rate=None) -> CapitalTransaction:
    return capital_service.record_transaction(
        db, created_by=None, project_id=p.id, source_type="自有资金", direction=direction,
        amount=amount, transaction_date=date(2026, 8, 10), currency_code=currency,
        settlement_rate=rate, idempotency_key=f"pay-{uuid.uuid4().hex[:8]}")


def _device(db, p, purchase_value, prepayment=Decimal("0")):
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    return dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                            purchase_value=purchase_value, prepayment_amount=prepayment)


def _approved_request(db, p, amount, **kw):
    pr = svc.create_request(db, project_id=p.id, amount=amount, **kw)
    approval_service.approve(db, pr.approval_id)
    return pr


# ------------------------------ 申请 / 审批 / 登记 ------------------------------

def test_request_prepayment_offset_validation(db):
    p = _project(db)
    with pytest.raises(BusinessError):  # 冲抵 ≥ 申请额
        svc.create_request(db, project_id=p.id, amount=Decimal("1000"),
                           prepayment_offset=Decimal("1000"))
    with pytest.raises(BusinessError):  # 冲抵超项目剩余预付款
        svc.create_request(db, project_id=p.id, amount=Decimal("1000"),
                           prepayment_offset=Decimal("100"))


def test_full_flow_with_prepayment_offset(db):
    """申请 1000 冲抵 300 → 登记：现金流水 700；设备预付款 FIFO 抵扣 300（单源）。"""
    p = _project(db)
    d1 = _device(db, p, Decimal("960000"), prepayment=Decimal("200"))
    d2 = _device(db, p, Decimal("960000"), prepayment=Decimal("200"))
    pr = _approved_request(db, p, Decimal("1000"), prepayment_offset=Decimal("300"))
    txn = svc.disburse(db, pr.id, transaction_date=date(2026, 8, 10))
    assert txn.amount == Decimal("700.00")  # 实付现金 = 1000 − 300
    d1 = db.get(Device, d1.id)
    d2 = db.get(Device, d2.id)
    assert d1.prepayment_settled_amount == Decimal("200.00") and d1.prepayment_settled is True
    assert d2.prepayment_settled_amount == Decimal("100.00")  # FIFO：先扣完 d1 再扣 d2
    assert db.get(type(pr), pr.id).status == "已付款"
    assert db.get(type(pr), pr.id).capital_transaction_id == txn.id


def test_disburse_before_approval_blocked(db):
    p = _project(db)
    pr = svc.create_request(db, project_id=p.id, amount=Decimal("1000"))
    with pytest.raises(BusinessError):
        svc.disburse(db, pr.id, transaction_date=date(2026, 8, 10))


def test_disburse_rejected_request_blocked(db):
    p = _project(db)
    pr = svc.create_request(db, project_id=p.id, amount=Decimal("1000"))
    approval_service.reject(db, pr.approval_id, reason="预算不足")
    with pytest.raises(BusinessError):
        svc.disburse(db, pr.id, transaction_date=date(2026, 8, 10))


# ------------------------------ 核销多对多 golden ------------------------------

def test_settle_one_txn_multi_invoices_golden(db):
    """一笔 1000 付款核销两张采购发票 600/400 → 两张都已核销 + paid_date 兜底；核销行 2 条。"""
    p = _project(db)
    c = _purchase_contract(db, p)
    i1 = _invoice(db, c, Decimal("600"))
    i2 = _invoice(db, c, Decimal("400"))
    txn = _txn(db, p, Decimal("1000"))
    rows = svc.settle(db, txn_id=txn.id, allocations=[
        {"invoice_id": i1.id, "amount": "600"},
        {"invoice_id": i2.id, "amount": "400"},
    ])
    assert len(rows) == 2
    for inv, amt in ((i1, "600"), (i2, "400")):
        inv2 = db.get(Invoice, inv.id)
        assert inv2.status == "已核销"
        assert inv2.paid_date == txn.transaction_date  # 核销满 → paid_date 兜底
    # matched_amount 新口径（含 payment_settlements）
    matched = db.execute(select(Invoice.matched_amount).where(Invoice.id == i1.id)).scalar()
    assert Decimal(matched) == Decimal("600.00")


def test_settle_multi_txn_same_invoice(db):
    """多笔核销同一发票：600 + 400 分两笔 → 第二笔后才已核销。"""
    p = _project(db)
    c = _purchase_contract(db, p)
    inv = _invoice(db, c, Decimal("1000"))
    t1 = _txn(db, p, Decimal("600"))
    t2 = _txn(db, p, Decimal("400"))
    svc.settle(db, txn_id=t1.id, allocations=[{"invoice_id": inv.id, "amount": "600"}])
    assert db.get(Invoice, inv.id).status != "已核销"
    svc.settle(db, txn_id=t2.id, allocations=[{"invoice_id": inv.id, "amount": "400"}])
    assert db.get(Invoice, inv.id).status == "已核销"


def test_settle_over_amount_and_direction_guard(db):
    p = _project(db)
    c = _purchase_contract(db, p)
    inv = _invoice(db, c, Decimal("500"))
    txn = _txn(db, p, Decimal("1000"))
    with pytest.raises(BusinessError):  # 核销合计超流水额
        svc.settle(db, txn_id=txn.id, allocations=[{"invoice_id": inv.id, "amount": "1001"}])
    # 方向：OUT 流水不可核销销售（RECEIVABLE）发票
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    sc = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                              amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    sinv = _invoice(db, sc, Decimal("100"))
    with pytest.raises(BusinessError):
        svc.settle(db, txn_id=txn.id, allocations=[{"invoice_id": sinv.id, "amount": "100"}])


def test_settle_unclaimed_allocation(db):
    """待认领：无 invoice_id 的核销行允许（invoice_id 可空）。"""
    p = _project(db)
    txn = _txn(db, p, Decimal("1000"))
    rows = svc.settle(db, txn_id=txn.id, allocations=[{"amount": "300"}])
    assert rows[0].invoice_id is None and rows[0].amount == Decimal("300")


# ------------------------------ 汇兑损益分摊至设备 ------------------------------

def test_fx_diff_split_to_devices_golden(db):
    """外币核销：USD 发票开票率 7.20 vs 结算率 7.10（付款付得少=收益 IN 1000）
    → 汇兑损益按设备价值 60万/40万 占比逐台拆 600/400（Σ 精确）。"""
    p = _project(db)
    c = _purchase_contract(db, p, currency="USD")
    inv = _invoice(db, c, Decimal("10000"), currency="USD", rate=Decimal("7.20"))
    txn = _txn(db, p, Decimal("10000"), currency="USD", rate=Decimal("7.10"))
    d1 = _device(db, p, Decimal("600000"))
    d2 = _device(db, p, Decimal("400000"))
    svc.settle(db, txn_id=txn.id, allocations=[{"invoice_id": inv.id, "amount": "10000"}])
    fx = db.execute(select(CapitalTransaction).where(
        CapitalTransaction.category == "汇兑损益")).scalars().one()
    assert fx.direction == "IN" and fx.amount == Decimal("1000.00")  # 付得少 = 收益
    rows = db.execute(select(PaymentSettlement).where(
        PaymentSettlement.capital_transaction_id == fx.id)).scalars().all()
    assert len(rows) == 2
    by_dev = {r.device_id: r.amount for r in rows}
    assert by_dev[d1.id] == Decimal("600.00") and by_dev[d2.id] == Decimal("400.00")
    assert sum(by_dev.values()) == Decimal("1000.00")
    # 幂等：重复结算同发票同流水不再出汇兑（fx:{txn}:{inv} 哨兵）——由超额拦截间接保证，此处直调钩子了 
