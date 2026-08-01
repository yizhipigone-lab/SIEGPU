"""验收记录服务单元测试。"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.master import Customer, EquipmentModel
from app.models.project import Project
from app.models.delivery import Order
from app.services import acceptance_service as svc


D = Decimal


@pytest.fixture
def order_id(db):
    """准备采购订单用于采购验收测试。"""
    cust = Customer(name="验收测试客户", industry="测试")
    db.add(cust); db.flush()
    eq = EquipmentModel(name="测卡", category="大卡", gpu_type="A100")
    db.add(eq); db.flush()
    p = Project(name="验收测试项目", code="TEST-ACCEPT", total_investment=D("100000"))
    db.add(p); db.flush()
    o = Order(project_id=p.id, equipment_model_id=eq.id, quantity=10,
              unit_price=D("10000"), total_amount=D("100000"))
    db.add(o); db.flush()
    return o.id, p.id


def test_create_purchase_acceptance(db, order_id):
    """采购验收：必须关联order_id。"""
    oid, pid = order_id
    ar = svc.create_acceptance(db, project_id=pid, acceptance_type="采购验收",
        order_id=oid, inspector="测试员", quantity_accepted=10)
    db.flush()
    assert ar.acceptance_type == "采购验收"
    assert ar.order_id == oid
    assert ar.status == "待验收"


def test_purchase_acceptance_missing_order_id(db, order_id):
    """采购验收缺少order_id应报错。"""
    oid, pid = order_id
    with pytest.raises(BusinessError) as exc:
        svc.create_acceptance(db, project_id=pid, acceptance_type="采购验收",
            order_id=None, inspector="测试员")
    assert exc.value.status_code == 422


def test_sales_acceptance_missing_sales_order_id(db, order_id):
    """销售验收缺少sales_order_id应报错。"""
    oid, pid = order_id
    with pytest.raises(BusinessError) as exc:
        svc.create_acceptance(db, project_id=pid, acceptance_type="销售验收",
            sales_order_id=None, inspector="测试员")
    assert exc.value.status_code == 422


def test_approve_acceptance(db, order_id):
    """验收通过流程。"""
    oid, pid = order_id
    ar = svc.create_acceptance(db, project_id=pid, acceptance_type="采购验收",
        order_id=oid, inspector="测试员")
    db.flush()
    ar = svc.approve_acceptance(db, ar, quantity_accepted=10,
        acceptance_date=date(2026, 6, 1))
    db.flush()
    assert ar.status == "已通过"
    assert ar.quantity_accepted == 10
    assert ar.acceptance_date == date(2026, 6, 1)


def test_reject_acceptance(db, order_id):
    """验收驳回流程。"""
    oid, pid = order_id
    ar = svc.create_acceptance(db, project_id=pid, acceptance_type="采购验收",
        order_id=oid, inspector="测试员")
    db.flush()
    ar = svc.reject_acceptance(db, ar, "设备损坏3台")
    db.flush()
    assert ar.status == "已驳回"
    assert ar.rejection_reason == "设备损坏3台"


def test_approve_twice_blocked(db, order_id):
    """已通过再调用approve应被挡。"""
    oid, pid = order_id
    ar = svc.create_acceptance(db, project_id=pid, acceptance_type="采购验收",
        order_id=oid)
    db.flush()
    svc.approve_acceptance(db, ar)
    db.flush()
    with pytest.raises(BusinessError):
        svc.approve_acceptance(db, ar)
