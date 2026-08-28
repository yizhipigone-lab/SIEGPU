"""四期 W4 期3：业务硬流转 5 条守卫的专项测试（正向放行 + 反向拦截）。

链：采购验收→在途发货→销售验收→对账单→开票→收入；验收(采购或销售)→金租放款。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.device import Device
from app.models.delivery import Order
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Project
from app.services import acceptance_service as acc
from app.services import billing_service as bsvc
from app.services import confirmation_service as conf
from app.services import contract_service as csvc
from app.services import device_service as dsvc
from app.services import invoice_service as isvc
from app.services import leasing_service as lsvc
from app.services import sales_order_service as so_svc

D = Decimal


def _project(db):
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush(); return e


def _sales_contract(db, p):
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}"); db.add(cust); db.flush()
    return csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                                amount=D("1000000"), tax_rate=D("0.13"))


def _approve_purchase(db, p, order_id):
    ar = acc.create_acceptance(db, project_id=p.id, acceptance_type="采购验收", order_id=order_id)
    acc.approve_acceptance(db, ar, approved_by=None)
    return ar


def _approve_sales(db, p, sales_order_id):
    ar = acc.create_acceptance(db, project_id=p.id, acceptance_type="销售验收", sales_order_id=sales_order_id)
    acc.approve_acceptance(db, ar, approved_by=None)
    return ar


def _batch_order_with_device(db, p, e):
    """采购批次订单 + 一台挂批次的设备（订货态）。"""
    b = Order(project_id=p.id, is_batch=True, batch_name="B")
    db.add(b); db.flush()
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           purchase_value=D("960000"), ownership="表内自有")
    dsvc.add_to_batch(db, device_id=d.id, batch_id=b.id)
    db.flush()
    return b, d


# ---- 门1：采购验收通过 → 才能推进「在途」 ----

def test_gate1_in_transit_blocked_without_purchase_acceptance(db):
    p = _project(db); e = _equipment(db)
    b, d = _batch_order_with_device(db, p, e)
    with pytest.raises(BusinessError):
        dsvc.advance_device_stage(db, device_id=d.id, stage="在途", status="进行中")


def test_gate1_in_transit_allowed_after_purchase_acceptance(db):
    p = _project(db); e = _equipment(db)
    b, d = _batch_order_with_device(db, p, e)
    _approve_purchase(db, p, b.id)
    dsvc.advance_device_stage(db, device_id=d.id, stage="在途", status="进行中")
    # 门放行：在途节点行已推进（device.status 物化列仍停在最早未完节点「订货」，故断言节点行）
    row = next(r for r in dsvc.list_device_stages(db, d.id) if r.stage == "在途")
    assert row.status == "进行中"


# ---- 门2：在途发货 → 才能销售验收 ----

def _sales_batch_with_device(db, p, c, e, device_status, lit=False):
    so = so_svc.create_sales_order(db, project_id=p.id, contract_id=c.id, equipment_model_id=e.id,
                                   quantity=1, monthly_rent_per_unit=D("1000"),
                                   total_monthly_rent=D("1000"), is_batch=True, batch_name="SB")
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           purchase_value=D("10000"), ownership="表内自有",
                           monthly_price=D("10000"))  # monthly_price：按台计费需要
    so_svc.add_to_sales_batch(db, device_id=d.id, sales_batch_id=so.id)
    d.status = device_status
    if lit:
        # 按台计费需设备点亮（读点亮阶段 actual_date）：置自动建的点亮行完成
        from app.models.device import DeviceStage
        _st = db.query(DeviceStage).filter_by(device_id=d.id, stage="点亮验收").one()
        _st.status = "已完成"; _st.actual_date = date(2026, 8, 1)
    db.flush()
    return so, d


def test_gate2_sales_acceptance_blocked_when_not_shipped(db):
    p = _project(db); e = _equipment(db); c = _sales_contract(db, p)
    so, d = _sales_batch_with_device(db, p, c, e, "订货")  # 仍在订货（未发货）
    with pytest.raises(BusinessError):
        acc.create_acceptance(db, project_id=p.id, acceptance_type="销售验收", sales_order_id=so.id)


def test_gate2_sales_acceptance_allowed_after_shipped(db):
    p = _project(db); e = _equipment(db); c = _sales_contract(db, p)
    so, d = _sales_batch_with_device(db, p, c, e, "在途")  # 已发货
    ar = acc.create_acceptance(db, project_id=p.id, acceptance_type="销售验收", sales_order_id=so.id)
    assert ar.status == "待验收"


# ---- 门3：销售验收通过 → 才能建客户对账单 ----

def test_gate3_confirmation_blocked_without_sales_acceptance(db):
    p = _project(db); e = _equipment(db); c = _sales_contract(db, p)
    so, d = _sales_batch_with_device(db, p, c, e, "点亮验收", lit=True)
    b = bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 8, 31), created_by=None)
    with pytest.raises(BusinessError):
        conf.create_confirmation(db, billing_id=b.id, sales_order_id=so.id, period_label="2026-08")


def test_gate3_confirmation_allowed_after_sales_acceptance(db):
    p = _project(db); e = _equipment(db); c = _sales_contract(db, p)
    so, d = _sales_batch_with_device(db, p, c, e, "点亮验收", lit=True)
    _approve_sales(db, p, so.id)
    b = bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 8, 31), created_by=None)
    sc = conf.create_confirmation(db, billing_id=b.id, sales_order_id=so.id, period_label="2026-08")
    assert sc.status == "待确认"


# ---- 门4：对账单确认 → 才能开票（销售批次流） ----

def test_gate4_invoice_blocked_without_confirmed_statement(db):
    p = _project(db); e = _equipment(db); c = _sales_contract(db, p)
    so, d = _sales_batch_with_device(db, p, c, e, "点亮验收", lit=True)  # 有销售订单 → 走对账门
    with pytest.raises(BusinessError):
        isvc.create_invoice(db, contract_id=c.id, amount=D("113000"), issue_date=date(2026, 8, 19))


def test_gate4_invoice_allowed_after_statement_confirmed(db):
    p = _project(db); e = _equipment(db); c = _sales_contract(db, p)
    so, d = _sales_batch_with_device(db, p, c, e, "点亮验收", lit=True)
    _approve_sales(db, p, so.id)
    b = bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id, period_index=1,
                                     billing_date=date(2026, 8, 31), created_by=None)
    sc = conf.create_confirmation(db, billing_id=b.id, sales_order_id=so.id, period_label="2026-08")
    conf.confirm(db, sc, confirmed_by_customer="客户A", operator_id=None)
    inv = isvc.create_invoice(db, contract_id=c.id, amount=D("113000"), issue_date=date(2026, 8, 19))
    assert inv.status == "已开"
    # 期2：开票即出收入确认草稿（不含税=发票不含税）
    from app.services import revenue_recognition_service as rsvc
    rec = rsvc.list_recognitions(db, project_id=p.id)[0]
    assert rec.invoice_id == inv.id and rec.amount == inv.amount_ex_tax


def test_gate4_standalone_contract_invoice_not_gated(db):
    """无销售订单的合同（一次性/非批次销售）不设对账前置，可直接开票。"""
    p = _project(db); c = _sales_contract(db, p)
    inv = isvc.create_invoice(db, contract_id=c.id, amount=D("113000"), issue_date=date(2026, 8, 19))
    assert inv.status == "已开"


# ---- 门5：验收(采购或销售)通过 → 才能金租放款 ----

def _leasing_process(db, p):
    sup = Supplier(name=f"金租-{uuid.uuid4().hex[:6]}", type="资金供应商", is_leasing_org=True)
    db.add(sup); db.flush()
    return lsvc.create_process(db, project_id=p.id, supplier_id=sup.id, total_amount=D("1000000"),
                               annual_rate=D("0.05"), term_periods=3, payment_freq="月",
                               repayment_method="等额本息")


def test_gate5_disburse_via_sales_acceptance(db):
    """销售验收也可作放款依据（期3 放宽：不再仅限采购验收）。"""
    p = _project(db); e = _equipment(db); c = _sales_contract(db, p)
    so, d = _sales_batch_with_device(db, p, c, e, "在途")
    ar = _approve_sales(db, p, so.id)
    proc = _leasing_process(db, p)
    d_rec, txn, n = lsvc.add_disbursement(db, process_id=proc.id, acceptance_id=ar.id,
                                          amount=D("500000"), disbursement_date=date(2026, 8, 19),
                                          created_by=None)
    assert txn.pool == "LEASING" and n > 0


def test_gate5_disburse_blocked_without_acceptance(db):
    p = _project(db)
    proc = _leasing_process(db, p)
    with pytest.raises(BusinessError):
        lsvc.add_disbursement(db, process_id=proc.id, acceptance_id=uuid.uuid4(),  # 不存在的验收
                              amount=D("500000"), disbursement_date=date(2026, 8, 19), created_by=None)
