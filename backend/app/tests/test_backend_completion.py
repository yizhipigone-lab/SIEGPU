"""后端补全测试：发票红冲、调配归还、资产折旧明细、应用内告警。"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.asset import Asset
from app.models.master import Customer, EquipmentModel
from app.models.project import Project
from app.services import alert_service
from app.services import asset_service as asvc
from app.services import capital_service as caps
from app.services import contract_service as csvc
from app.services import invoice_service as isvc
from app.services import leasing_service as lsvc
from app.services import order_service as osvc


def _user_p(db):
    from app.models.user import User
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u); db.flush(); return u


def _proj(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


# ---------- 发票红冲 ----------
def test_invoice_reverse_excludes_from_recon(db):
    p = _proj(db); cust = Customer(name="c"); db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("100000"))
    # 红冲前：对账含该发票
    row = [r for r in isvc.reconciliation(db) if r["contract_id"] == str(c.id)][0]
    assert row["invoiced"] > 0
    isvc.reverse_invoice(db, invoice_id=inv.id, reversed_by=uuid.uuid4())
    # 红冲后：原票与红冲凭证均剔除 → invoiced 归零
    row2 = [r for r in isvc.reconciliation(db) if r["contract_id"] == str(c.id)][0]
    assert row2["invoiced"] == Decimal("0.00")


# ---------- 调配归还 ----------
def test_allocation_return_net_zero_and_status(db):
    u = _user_p(db); a = _proj(db); b = _proj(db)
    caps.record_transaction(db, created_by=u.id, project_id=a.id, source_type="自有资金",
                            direction="IN", amount=Decimal("5000000"), transaction_date=date(2026, 1, 1))
    alloc = caps.allocate(db, approved_by=u.id, from_project_id=a.id, to_project_id=b.id,
                          amount=Decimal("3000000"), allocation_date=date(2026, 1, 2))
    before = caps.pool_summary(db)["pool_balance"]
    caps.return_allocation(db, allocation_id=alloc.id, returned_by=u.id, return_date=date(2026, 2, 1))
    after = caps.pool_summary(db)["pool_balance"]
    assert before == after  # 归还也是净 0，池余额不变
    fresh = db.get(type(alloc), alloc.id)
    assert fresh.status == "已归还" and fresh.actual_return_date == date(2026, 2, 1)


# ---------- 资产折旧明细 ----------
def test_depreciation_schedule_sums_to_depreciable(db):
    p = _proj(db); eq = EquipmentModel(name="H100", category="大卡"); db.add(eq); db.flush()
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id, quantity=10, unit_price=Decimal("100000"))
    osvc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    asset = db.execute(select(Asset).where(Asset.order_id == o.id)).scalar_one()
    sched = asvc.depreciation_schedule(db, asset.id)
    assert len(sched) == 60
    assert sum(r["amount"] for r in sched) == Decimal("900000.00")  # 1M×0.9，末期吸收尾差精确闭合


# ---------- 应用内告警 ----------
def test_alerts_overdue_repayment(db):
    u = _user_p(db); p = _proj(db)
    from app.models.master import Supplier
    sup = Supplier(name="金租A", type="资金供应商"); db.add(sup); db.flush()
    proc = lsvc.create_process(db, project_id=p.id, supplier_id=sup.id, total_amount=Decimal("1000000"),
                               annual_rate=Decimal("0.05"), term_periods=4, payment_freq="季",
                               repayment_method="等额本金", start_date=date(2026, 1, 1))
    proc.status = "已批"; db.flush()
    # 放款日设在 2 年前 → 多期已逾期
    lsvc.disburse(db, process_id=proc.id, actual_disbursement_amount=Decimal("1000000"),
                  disbursement_date=date.today() - timedelta(days=730), disbursed_by=u.id)
    alerts = alert_service.compute_alerts(db)
    assert any(a["code"] == "REPAYMENT_OVERDUE" for a in alerts)
