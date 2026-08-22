"""v3.2 新增查询端点测试：pool-by-project / allocations / portfolio / project-comparison / matched_amount。"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.master import Customer
from app.models.project import Project
from app.models.user import User
from app.schemas.invoice import InvoiceOut
from app.services import capital_service as caps
from app.services import contract_service as csvc
from app.services import invoice_service as isvc
from app.services import profit_service as psvc
from app.services import report_service as rsvc
from app.services import workflow_service as wfsvc

D = Decimal


def _user(db):
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u); db.flush(); return u


def _proj(db, name="P"):
    p = Project(name=name, code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


# ---------- b) GET /api/capital/pool-by-project ----------
def test_pool_by_project_net_position_and_allocatable(db):
    u = _user(db); p = _proj(db, name="净头寸项目")
    caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                            direction="IN", amount=D("1000000"), transaction_date=date(2026, 1, 1))
    caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                            direction="OUT", amount=D("400000"), transaction_date=date(2026, 1, 2))

    rows = caps.pool_by_project(db)
    row = next(r for r in rows if r["project_id"] == str(p.id))
    assert row["project_name"] == "净头寸项目"
    assert row["net_position"] == 600000.0
    assert row["allocatable"] == 600000.0
    assert row["in_transit"] == 0.0


# ---------- c) GET /api/capital/allocations ----------
def test_list_allocations_after_allocate(db):
    u = _user(db); a = _proj(db); b = _proj(db)
    caps.record_transaction(db, created_by=u.id, project_id=a.id, source_type="自有资金",
                            direction="IN", amount=D("500000"), transaction_date=date(2026, 1, 1))
    alloc = caps.allocate(db, approved_by=u.id, from_project_id=a.id, to_project_id=b.id,
                          amount=D("200000"), allocation_date=date(2026, 1, 2), reason="周转")

    rows = caps.list_allocations(db)
    assert [r.id for r in rows] == [alloc.id]
    assert rows[0].status == "已调配" and rows[0].amount == D("200000")
    # project_id 过滤：调出/调入双向命中
    assert [r.id for r in caps.list_allocations(db, project_id=a.id)] == [alloc.id]
    assert [r.id for r in caps.list_allocations(db, project_id=b.id)] == [alloc.id]
    assert caps.list_allocations(db, project_id=_proj(db).id) == []


# ---------- d) GET /api/workflows/portfolio ----------
def test_portfolio_returns_current_step_and_status(db):
    p = _proj(db, name="组合项目")
    wf = wfsvc.create_workflow(db, project_id=p.id)

    rows = wfsvc.portfolio(db)
    row = next(r for r in rows if r["project_id"] == str(p.id))
    assert row["project_name"] == "组合项目"
    assert row["current_step"] == wf.current_step
    assert row["current_step_name"]
    assert row["status"] == wf.status
    assert row["total_steps"] == 18 and "done_count" in row


# ---------- e) GET /api/reports/project-comparison ----------
def test_project_comparison_returns_irr_and_collection_fields(db):
    p = _proj(db, name="对比项目")
    psvc.save_scenario(db, project_id=p.id, name="实际", params_json={},
                       result_json={"summary": {"irr_annual_pct": 12.5, "npv_5pct": 880000,
                                                "total_profit": 1500000}},
                       is_actual=True)

    rows = rsvc.project_comparison(db)
    row = next(r for r in rows if r["project_id"] == str(p.id))
    assert row["project_name"] == "对比项目"
    assert row["irr"] == 12.5 and row["npv"] == 880000 and row["total_profit"] == 1500000
    assert row["collection_rate"] is None  # 无计费 → 回款率为 None
    assert row["overdue_count"] == 0 and row["progress_pct"] == 0


# ---------- f) 发票 matched_amount：核销后 = 已关联核销流水金额合计 ----------
def test_invoice_matched_amount_after_reconcile(db):
    u = _user(db); p = _proj(db)
    cust = Customer(name=f"cust{uuid.uuid4().hex[:6]}"); db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=D("1000000"), tax_rate=D("0.13"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=D("113000"))

    # 部分核销 50000
    t1 = caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="租金收入",
                                 direction="IN", amount=D("50000"), transaction_date=date(2026, 3, 1))
    isvc.reconcile_invoice(db, invoice_id=inv.id, txn_id=t1.id, reconciled_by=u.id)
    out = InvoiceOut.model_validate(isvc.list_invoices(db, contract_id=c.id)[0])
    assert out.matched_amount == D("50000")
    assert out.status != "已核销"

    # 再核销 63000 → 全额，matched_amount 覆盖发票全额
    t2 = caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="租金收入",
                                 direction="IN", amount=D("63000"), transaction_date=date(2026, 3, 2))
    isvc.reconcile_invoice(db, invoice_id=inv.id, txn_id=t2.id, reconciled_by=u.id)
    out2 = InvoiceOut.model_validate(isvc.list_invoices(db, contract_id=c.id)[0])
    assert out2.matched_amount == D("113000")
    assert out2.status == "已核销"


def test_invoice_matched_amount_defaults_zero(db):
    u = _user(db); p = _proj(db)
    cust = Customer(name=f"cust{uuid.uuid4().hex[:6]}"); db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=D("1000000"), tax_rate=D("0.13"))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=D("100000"))
    out = InvoiceOut.model_validate(isvc.list_invoices(db, contract_id=c.id)[0])
    assert out.matched_amount == D("0")
    assert inv.status == "已开"


# ---------- 项目总览增强：财务聚合列 ----------
def test_portfolio_financial_aggregates(db):
    """portfolio 每项目带 销售合同额(含税优先)/金租放款/预付余额 三个聚合字段。"""
    from app.models.device import Device
    from app.models.leasing import LeasingProcess
    from app.models.master import EquipmentModel, Supplier

    p = _proj(db, name="聚合项目")
    wfsvc.create_workflow(db, project_id=p.id)
    cust = Customer(name=f"c{uuid.uuid4().hex[:6]}")
    sup = Supplier(name=f"s{uuid.uuid4().hex[:6]}", type="资金供应商")
    db.add_all([cust, sup]); db.flush()
    # 销售合同：含税 1000（amount_incl_tax 优先于不含税 amount）
    csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                         amount=D("900"), tax_rate=D("0.13"), amount_incl_tax=D("1000"))
    # 金租放款 600（多笔放款口径：Σ leasing_disbursements.amount——
    # add_disbursement 不回写 actual_disbursement_amount，只有旧一次性 disburse 写）
    from datetime import date as _date

    from app.models.leasing import LeasingDisbursement
    lp = LeasingProcess(project_id=p.id, supplier_id=sup.id, total_amount=D("800"), status="已放款")
    db.add(lp); db.flush()
    db.add(LeasingDisbursement(process_id=lp.id, amount=D("600"),
                               disbursement_date=_date(2026, 2, 1)))
    # 设备预付 500 未结清 + 400 已回核销（只计剩余）
    em = EquipmentModel(name=f"em{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(em); db.flush()
    db.add(Device(sn=f"GPU-{uuid.uuid4().hex[:8]}", project_id=p.id, equipment_model_id=em.id,
                  prepayment_amount=D("500")))
    db.add(Device(sn=f"GPU-{uuid.uuid4().hex[:8]}", project_id=p.id, equipment_model_id=em.id,
                  prepayment_amount=D("400"), prepayment_settled=True,
                  prepayment_settled_amount=D("400")))
    db.flush()

    rows = wfsvc.portfolio(db)
    row = next(r for r in rows if r["project_id"] == str(p.id))
    assert row["sales_total"] == 1000.0
    assert row["leasing_disbursed"] == 600.0
    assert row["prepay_remaining"] == 500.0

    # 无业务项目：三字段为 0 且不报错
    p2 = _proj(db, name="空项目")
    wfsvc.create_workflow(db, project_id=p2.id)
    rows2 = wfsvc.portfolio(db)
    row2 = next(r for r in rows2 if r["project_id"] == str(p2.id))
    assert row2["sales_total"] == 0.0 and row2["leasing_disbursed"] == 0.0 and row2["prepay_remaining"] == 0.0
