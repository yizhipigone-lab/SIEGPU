"""币种与汇率测试（二期 W5-6）：币种/汇率 CRUD + 取值规则 + 汇兑损益 golden（正/负/零/精度）。

量纲依据：docs/superpowers/specs/2026-08-12-w5-6-unit-dimension-table.md（D6 对照表，动工前已出）。
golden 算例真值见对照表 §4（G1 收益 / G2 损失 / G3 零 / G4 精度 / G5 base_amount）。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.exceptions import BusinessError
from app.models.billing import Invoice
from app.models.capital import CapitalTransaction
from app.models.master import Customer, Supplier
from app.models.project import Project
from app.services import capital_service, contract_service, exchange_service as fx
from app.services import invoice_service


def _project(db) -> Project:
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p)
    db.flush()
    return p


def _usd_contract(db, p):
    cust = Customer(name=f"FX客户-{uuid.uuid4().hex[:6]}")
    db.add(cust)
    db.flush()
    return contract_service.create_contract(
        db, project_id=p.id, type="SALES", party_id=cust.id,
        amount=Decimal("1000000"), tax_rate=Decimal("0.13"), currency_code="USD")


def _usd_invoice(db, contract, rate: str, amount=Decimal("10000")) -> Invoice:
    return invoice_service.create_invoice(
        db, contract_id=contract.id, amount=amount,
        invoice_no=f"INV-FX-{uuid.uuid4().hex[:6]}", issue_date=date(2026, 8, 1),
        invoice_rate=Decimal(rate))


def _usd_txn(db, p, rate: str, amount=Decimal("10000"), direction="IN"):
    return capital_service.record_transaction(
        db, created_by=None, project_id=p.id, source_type="租金收入", direction=direction,
        amount=amount, transaction_date=date(2026, 8, 10), currency_code="USD",
        settlement_rate=Decimal(rate),
        base_amount=fx.to_base(amount, Decimal(rate)),
        idempotency_key=f"fxtest-{uuid.uuid4().hex[:8]}")


def _fx_txns(db, invoice: Invoice):
    return db.execute(select(CapitalTransaction).where(
        CapitalTransaction.category == "汇兑损益",
        CapitalTransaction.contract_id == invoice.contract_id)).scalars().all()


# ------------------------------ 币种 CRUD ------------------------------

def test_currency_crud_and_single_base(db):
    cny = fx.create_currency(db, code="cny", name="人民币", symbol="¥", is_base=True)
    assert cny.code == "CNY"  # 归一大写
    assert fx.base_currency_code(db) == "CNY"
    usd = fx.create_currency(db, code="USD", name="美元", symbol="$")
    assert usd.is_base is False
    with pytest.raises(BusinessError):  # 重复 code → 409
        fx.create_currency(db, code="usd", name="美元2")
    # 设 USD 为本币 → CNY 自动退位（本币恰好一个）
    fx.update_currency(db, usd.id, {"is_base": True})
    assert fx.base_currency_code(db) == "USD"
    assert db.get(type(cny), cny.id).is_base is False


def test_base_currency_fallback_cny(db):
    """未配置任何币种时本币回退 CNY（对照表：currency NULL=人民币）。"""
    assert fx.base_currency_code(db) == "CNY"


# ------------------------------ 汇率取值（最近不未来） ------------------------------

def test_rate_lookup_latest_not_future(db):
    fx.add_rate(db, from_currency="USD", to_currency="CNY", rate=Decimal("7.10"),
                effective_date=date(2026, 8, 1), source="央行")
    fx.add_rate(db, from_currency="USD", to_currency="CNY", rate=Decimal("7.20"),
                effective_date=date(2026, 8, 10), source="央行")
    fx.add_rate(db, from_currency="USD", to_currency="CNY", rate=Decimal("9.99"),
                effective_date=date(2026, 12, 31), source="央行")  # 未来，绝不取
    assert fx.get_rate(db, "USD", "CNY", date(2026, 8, 10)) == Decimal("7.20")
    assert fx.get_rate(db, "USD", "CNY", date(2026, 8, 5)) == Decimal("7.10")   # 取 8-01 的
    assert fx.get_rate(db, "usd", "cny", date(2026, 8, 20)) == Decimal("7.20")   # 大小写不敏感
    with pytest.raises(BusinessError):  # 7 月无任何记录 → 报错，不静默按 1
        fx.get_rate(db, "USD", "CNY", date(2026, 7, 1))


def test_rate_same_currency_is_one(db):
    assert fx.get_rate(db, "CNY", "CNY", date(2026, 8, 1)) == Decimal(1)  # 不查表


def test_rate_reject_non_positive(db):
    with pytest.raises(BusinessError):
        fx.add_rate(db, from_currency="USD", to_currency="CNY", rate=Decimal("0"),
                    effective_date=date(2026, 8, 1))


def test_to_base_golden_g5(db):
    """G5：USD 10,000 × 7.12345678 = 71,234.57（全精度率参与，仅最终 q2）。"""
    assert fx.to_base(Decimal("10000"), Decimal("7.12345678")) == Decimal("71234.57")


# ------------------------------ 汇兑损益 golden（核销钩子） ------------------------------

def test_gain_golden_g1(db):
    """G1 收益：USD 10,000，开票率 7.10 < 结算率 7.20 → 收得多 → IN 1,000.00。"""
    p = _project(db)
    c = _usd_contract(db, p)
    inv = _usd_invoice(db, c, "7.10")
    txn = _usd_txn(db, p, "7.20")
    invoice_service.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=None)
    rows = _fx_txns(db, inv)
    assert len(rows) == 1
    assert rows[0].direction == "IN" and rows[0].amount == Decimal("1000.00")
    assert rows[0].source_type == "汇兑损益" and rows[0].currency_code is None  # 已是人民币
    assert rows[0].invoice_id is None  # 不填 invoice_id（防 matched_amount 污染）
    # 核销口径不被损益污染：matched 仍 = 结算流水 10,000，不含损益 1,000
    matched = db.execute(select(func.coalesce(func.sum(CapitalTransaction.amount), 0)).where(
        CapitalTransaction.invoice_id == inv.id)).scalar()
    assert matched == Decimal("10000.00")


def test_loss_golden_g2(db):
    """G2 损失：开票率 7.20 > 结算率 7.10 → 收得少 → OUT 1,000.00。"""
    p = _project(db)
    inv = _usd_invoice(db, _usd_contract(db, p), "7.20")
    txn = _usd_txn(db, p, "7.10")
    invoice_service.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=None)
    rows = _fx_txns(db, inv)
    assert len(rows) == 1
    assert rows[0].direction == "OUT" and rows[0].amount == Decimal("1000.00")


def test_zero_diff_no_record_g3(db):
    """G3 零：开票率 = 结算率 → 不落任何汇兑损益记录。"""
    p = _project(db)
    inv = _usd_invoice(db, _usd_contract(db, p), "7.10")
    txn = _usd_txn(db, p, "7.10")
    invoice_service.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=None)
    assert _fx_txns(db, inv) == []


def test_precision_golden_g4(db):
    """G4 精度：33,333.33 × (7.12345678 − 7.10) = 781.8925…→ 781.89（率全精度，仅最终 q2）。"""
    diff = fx.compute_exchange_diff(Decimal("33333.33"), Decimal("7.12345678"), Decimal("7.10000000"))
    assert diff == Decimal("781.89")


def test_payable_direction_reversed(db):
    """采购付款：开票率 7.20 > 结算率 7.10 → 付得少 = 收益 IN（方向与应收相反）。"""
    p = _project(db)
    sup = Supplier(name=f"FX供应商-{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add(sup)
    db.flush()
    parent = _usd_contract(db, p)  # 参照同项目销售合同
    c = contract_service.create_contract(
        db, project_id=p.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("1000000"), tax_rate=Decimal("0.13"), currency_code="USD",
        parent_contract_id=parent.id)
    inv = _usd_invoice(db, c, "7.20")
    assert inv.direction == "PAYABLE"
    txn = _usd_txn(db, p, "7.10", direction="OUT")
    invoice_service.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=None)
    rows = _fx_txns(db, inv)
    assert len(rows) == 1
    assert rows[0].direction == "IN" and rows[0].amount == Decimal("1000.00")


def test_cny_reconcile_no_fx(db):
    """人民币（或未填币种）核销：不产生汇兑损益（零回归：一期所有核销路径不受影响）。"""
    p = _project(db)
    cust = Customer(name=f"FX客户-{uuid.uuid4().hex[:6]}")
    db.add(cust)
    db.flush()
    c = contract_service.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                                         amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    inv = invoice_service.create_invoice(db, contract_id=c.id, amount=Decimal("10000"),
                                         issue_date=date(2026, 8, 1))
    txn = capital_service.record_transaction(
        db, created_by=None, project_id=p.id, source_type="租金收入", direction="IN",
        amount=Decimal("10000"), transaction_date=date(2026, 8, 10),
        idempotency_key=f"fxtest-{uuid.uuid4().hex[:8]}")
    invoice_service.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=None)
    assert _fx_txns(db, inv) == []
    assert inv.status == "已核销"  # 原有核销行为不变


def test_fx_idempotent_same_txn(db):
    """同一结算流水重复触发钩子 → 只落一条（fx:{txn.id} 幂等守卫）。"""
    p = _project(db)
    inv = _usd_invoice(db, _usd_contract(db, p), "7.10")
    txn = _usd_txn(db, p, "7.20")
    first = fx.maybe_book_exchange_diff(db, invoice=inv, txn=txn, actor_id=None)
    second = fx.maybe_book_exchange_diff(db, invoice=inv, txn=txn, actor_id=None)
    assert first is not None and second is None
    assert len(_fx_txns(db, inv)) == 1


def test_billing_inherits_contract_currency(db):
    """计费单继承合同币种 + 按计费日取 booked_rate（最近不未来）。"""
    from app.services import billing_service
    from app.models.device import Device
    from app.models.master import EquipmentModel

    fx.add_rate(db, from_currency="USD", to_currency="CNY", rate=Decimal("7.15"),
                effective_date=date(2026, 8, 1))
    p = _project(db)
    c = _usd_contract(db, p)
    m = EquipmentModel(name=f"FX型号-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(m)
    db.flush()
    d = Device(project_id=p.id, equipment_model_id=m.id, sn=f"GPU-FX-{uuid.uuid4().hex[:6]}",
               sales_contract_id=c.id, monthly_price=Decimal("10000"),
               ownership="表内自有", leasing_mode="自有", status="点亮验收")
    db.add(d)
    db.flush()
    from app.models.device import DeviceStage
    st = DeviceStage(device_id=d.id, stage="点亮验收", seq=7, status="已完成",
                     actual_date=date(2026, 8, 1))
    db.add(st)
    db.flush()
    b = billing_service.generate_billing_device(
        db, device_id=d.id, contract_id=c.id, period_index=1,
        billing_date=date(2026, 8, 31), created_by=None)
    assert b.currency_code == "USD"
    assert b.booked_rate == Decimal("7.15000000")  # DECIMAL(18,8) 全精度
