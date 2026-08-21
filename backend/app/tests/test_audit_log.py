"""审计留痕测试：关键业务动作写入 audit_logs + user_id 降级路径。"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Project
from app.models.user import AuditLog, User
from app.services import acceptance_service as accsvc
from app.services import audit_service as audit
from app.services import capital_service as caps
from app.services import contract_service as csvc
from app.services import invoice_service as isvc
from app.services import leasing_service as lsvc
from app.services import order_service as osvc

D = Decimal


def _user(db):
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u); db.flush(); return u


def _proj(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


def _logs(db):
    return db.execute(select(AuditLog)).scalars().all()


# ---------- 放款 → DISBURSE + SUPERSEDE ----------
def test_disburse_writes_disburse_and_supersede(db):
    u = _user(db); p = _proj(db)
    fin = Supplier(name=f"fin{uuid.uuid4().hex[:6]}", type="资金供应商"); db.add(fin); db.flush()
    # 项目内有一笔未置换的流贷付款 → 放款时应触发资金置换（SUPERSEDE）
    caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                            direction="IN", amount=D("500000"), transaction_date=date(2026, 1, 1))
    caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                            direction="OUT", amount=D("300000"), transaction_date=date(2026, 1, 2))
    proc = lsvc.create_process(db, project_id=p.id, supplier_id=fin.id, total_amount=D("600000"),
                               annual_rate=D("0.05"), term_periods=4, payment_freq="季",
                               repayment_method="等额本金", start_date=date(2026, 1, 1))
    lsvc.disburse(db, process_id=proc.id, actual_disbursement_amount=D("600000"),
                  disbursement_date=date(2026, 2, 1), disbursed_by=u.id)

    logs = _logs(db)
    disb = [l for l in logs if l.action == "DISBURSE"]
    sup = [l for l in logs if l.action == "SUPERSEDE"]
    assert len(disb) == 1 and disb[0].entity_type == "leasing_process" and disb[0].entity_id == proc.id
    assert disb[0].user_id == u.id and disb[0].after_json["amount"] == "600000"
    assert len(sup) == 1 and sup[0].entity_type == "funding_replacement"
    assert sup[0].after_json["amount"] == "300000.00"  # 流贷付款被全额置换


# ---------- 发票核销 → RECONCILE ----------
def test_reconcile_invoice_writes_reconcile(db):
    u = _user(db); p = _proj(db)
    cust = Customer(name=f"cust{uuid.uuid4().hex[:6]}"); db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=D("1000000"), tax_rate=D("0.13"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=D("100000"))
    txn = caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="租金收入",
                                  direction="IN", amount=D("100000"), transaction_date=date(2026, 3, 1))
    isvc.reconcile_invoice(db, invoice_id=inv.id, txn_id=txn.id, reconciled_by=u.id)

    rec = [l for l in _logs(db) if l.action == "RECONCILE"]
    assert len(rec) == 1
    assert rec[0].entity_type == "invoice" and rec[0].entity_id == inv.id
    assert rec[0].user_id == u.id and rec[0].after_json["matched"] == "100000.00"


# ---------- 流水红冲 → REVERSE ----------
def test_reverse_transaction_writes_reverse(db):
    u = _user(db); p = _proj(db)
    txn = caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                                  direction="IN", amount=D("80000"), transaction_date=date(2026, 1, 5))
    caps.reverse_transaction(db, txn_id=txn.id, reversed_by=u.id)

    rev = [l for l in _logs(db) if l.action == "REVERSE"]
    assert len(rev) == 1
    assert rev[0].entity_type == "capital_transaction" and rev[0].entity_id == txn.id
    assert rev[0].user_id == u.id and rev[0].after_json["amount"] == "80000"


# ---------- 调配 → ALLOCATE；归还 → ALLOCATE_RETURN ----------
def test_allocate_and_return_write_audit(db):
    u = _user(db); a = _proj(db); b = _proj(db)
    caps.record_transaction(db, created_by=u.id, project_id=a.id, source_type="自有资金",
                            direction="IN", amount=D("500000"), transaction_date=date(2026, 1, 1))
    alloc = caps.allocate(db, approved_by=u.id, from_project_id=a.id, to_project_id=b.id,
                          amount=D("200000"), allocation_date=date(2026, 1, 2))
    caps.return_allocation(db, allocation_id=alloc.id, returned_by=u.id, return_date=date(2026, 2, 1))

    logs = _logs(db)
    al = [l for l in logs if l.action == "ALLOCATE"]
    rt = [l for l in logs if l.action == "ALLOCATE_RETURN"]
    assert len(al) == 1 and al[0].entity_type == "capital_allocation" and al[0].entity_id == alloc.id
    assert al[0].user_id == u.id and al[0].after_json["amount"] == "200000"
    assert len(rt) == 1 and rt[0].entity_type == "capital_allocation" and rt[0].entity_id == alloc.id
    assert rt[0].after_json["return_date"] == "2026-02-01"


# ---------- 验收通过 → ACCEPT_APPROVE ----------
def test_approve_acceptance_writes_accept_approve(db):
    u = _user(db); p = _proj(db)
    eq = EquipmentModel(name="H100", category="大卡"); db.add(eq); db.flush()
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id, quantity=5,
                          unit_price=D("80000"))
    ar = accsvc.create_acceptance(db, project_id=p.id, acceptance_type="采购验收", order_id=o.id)
    accsvc.approve_acceptance(db, ar, quantity_accepted=5, approved_by=u.id)

    aa = [l for l in _logs(db) if l.action == "ACCEPT_APPROVE"]
    assert len(aa) == 1
    assert aa[0].entity_type == "acceptance_record" and aa[0].entity_id == ar.id
    assert aa[0].user_id == u.id and aa[0].after_json["status"] == "已通过"


# ---------- 点亮 → LIGHT_ON ----------
def test_light_on_writes_light_on(db):
    u = _user(db); p = _proj(db)
    eq = EquipmentModel(name="H100", category="大卡"); db.add(eq); db.flush()
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id, quantity=5,
                          unit_price=D("80000"))
    osvc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15), operator_id=u.id)

    lo = [l for l in _logs(db) if l.action == "LIGHT_ON"]
    assert len(lo) == 1
    assert lo[0].entity_type == "order" and lo[0].entity_id == o.id
    assert lo[0].user_id == u.id and lo[0].after_json["date"] == "2026-09-15"


# ---------- 降级路径：user_id 不存在 → 仍写入且 user_id 为 None ----------
def test_audit_log_unknown_user_degrades_to_null(db):
    ghost = uuid.uuid4()  # 不在 users 表
    audit.log(db, user_id=ghost, action="DISBURSE", target_type="leasing_process",
              target_id=None, after_json={"amount": "1"})
    db.flush()

    logs = _logs(db)
    assert len(logs) == 1
    assert logs[0].user_id is None
    assert logs[0].action == "DISBURSE" and logs[0].entity_type == "leasing_process"


def test_capital_txn_writes_audit(db):
    """CAPITAL_TXN：资金记账写入审计日志。"""
    u = _user(db); p = _proj(db)
    caps.record_transaction(db, created_by=u.id, project_id=p.id,
                             source_type="自有资金", direction="IN",
                             amount=Decimal("100000"), transaction_date=date(2026, 1, 2))
    db.flush()
    logs = db.execute(select(AuditLog).where(AuditLog.action == "CAPITAL_TXN")).scalars().all()
    assert len(logs) >= 1
    assert logs[0].user_id == u.id
    assert logs[0].entity_type == "capital_transaction"
    assert "source_type" in (logs[0].after_json or {})


def test_confirm_upload_writes_audit(db):
    """CONFIRM_UPLOAD：客户确认写入审计日志。"""
    u = _user(db); p = _proj(db)
    cust = Customer(name="确认测客"); db.add(cust); db.flush()
    eq = EquipmentModel(name="确认卡", category="大卡"); db.add(eq); db.flush()
    from app.services import sales_order_service as sos, order_service as osvc
    from app.services import billing_service as bsvc, confirmation_service as csvc2
    ct = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                               amount=Decimal("1000000"), tax_rate=Decimal("0.06"),
                               monthly_rent=Decimal("100000"))
    so = sos.create_sales_order(db, project_id=p.id, contract_id=ct.id,
                                 equipment_model_id=eq.id, quantity=10,
                                 monthly_rent_per_unit=Decimal("10000"),
                                 total_monthly_rent=Decimal("100000"))
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id,
                           quantity=10, unit_price=Decimal("5000"))
    from app.models.delivery import DeliveryStage
    stages = db.execute(select(DeliveryStage).where(DeliveryStage.order_id == o.id).order_by(DeliveryStage.seq)).scalars().all()
    for s in stages:
        s.status = "已完成"; s.actual_date = date(2026, 7, 1)
    db.flush()
    osvc.light_on(db, order_id=o.id, actual_date=date(2026, 7, 1))
    db.flush()
    b = bsvc.generate_billing(db, order_id=o.id, contract_id=ct.id, period_index=1,
                                billing_date=date(2026, 7, 31), created_by=u.id)
    db.flush()
    # 四期 W4 期3 硬流转#3：建对账单（确认单）前须有已通过的销售验收
    from app.services import acceptance_service as asvc
    _ar = asvc.create_acceptance(db, project_id=p.id, acceptance_type="销售验收", sales_order_id=so.id)
    asvc.approve_acceptance(db, _ar, approved_by=u.id)
    db.flush()
    sc = csvc2.create_confirmation(db, billing_id=b.id, sales_order_id=so.id,
                                    period_label="2026-07", created_by=u.id)
    db.flush()
    csvc2.confirm(db, sc, confirmed_by_customer="测客", operator_id=u.id)
    db.flush()
    logs = db.execute(select(AuditLog).where(AuditLog.action == "CONFIRM_UPLOAD")).scalars().all()
    assert len(logs) >= 1
    assert logs[0].entity_type == "service_confirmation"
    assert "customer" in (logs[0].after_json or {})
