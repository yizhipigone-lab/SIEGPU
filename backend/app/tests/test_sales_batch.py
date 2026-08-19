"""销售批次组合服务测试（W4）。"""
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.device import Device
from app.models.master import Customer, EquipmentModel
from app.models.project import Contract, Project
from app.models.sales_order import SalesOrder
from app.services import sales_order_service as svc

D = Decimal


@pytest.fixture
def sales_batch(db):
    cust = Customer(name="销售批次客户", industry="测试")
    db.add(cust); db.flush()
    eq = EquipmentModel(name="批测卡", category="大卡", gpu_type="A100")
    db.add(eq); db.flush()
    p = Project(name="销售批次项目", code="TEST-SB", total_investment=D("100000"))
    db.add(p); db.flush()
    c = Contract(project_id=p.id, type="SALES", party_type="customer", party_id=cust.id,
                 direction="RECEIVABLE", amount=D("100000"), tax_rate=D("0.06"))
    db.add(c); db.flush()
    so = SalesOrder(project_id=p.id, contract_id=c.id, equipment_model_id=eq.id,
                    quantity=2, monthly_rent_per_unit=D("1000"), total_monthly_rent=D("2000"),
                    is_batch=True, batch_name="销售批次1")
    db.add(so); db.flush()
    d1 = Device(project_id=p.id, equipment_model_id=eq.id, sn="GPU-SB-00001")
    d2 = Device(project_id=p.id, equipment_model_id=eq.id, sn="GPU-SB-00002")
    db.add_all([d1, d2]); db.flush()
    return {"so": so, "devices": [d1, d2], "p": p}


def test_add_to_sales_batch(db, sales_batch):
    so = sales_batch["so"]
    d1 = sales_batch["devices"][0]
    bd = svc.add_to_sales_batch(db, device_id=d1.id, sales_batch_id=so.id)
    db.flush()
    assert bd.active is True
    assert bd.sales_batch_id == so.id
    assert bd.device_id == d1.id


def test_add_duplicate_sales_batch_blocked(db, sales_batch):
    so = sales_batch["so"]
    d1 = sales_batch["devices"][0]
    svc.add_to_sales_batch(db, device_id=d1.id, sales_batch_id=so.id)
    db.flush()
    with pytest.raises(BusinessError):
        svc.add_to_sales_batch(db, device_id=d1.id, sales_batch_id=so.id)


def test_remove_from_sales_batch(db, sales_batch):
    so = sales_batch["so"]
    d1 = sales_batch["devices"][0]
    svc.add_to_sales_batch(db, device_id=d1.id, sales_batch_id=so.id)
    db.flush()
    svc.remove_from_sales_batch(db, device_id=d1.id)
    db.flush()
    rows = svc.list_sales_batch_devices(db, sales_batch_id=so.id)
    assert all(r.active is False for r in rows)


def test_list_sales_batch_devices(db, sales_batch):
    so = sales_batch["so"]
    d1 = sales_batch["devices"][0]
    svc.add_to_sales_batch(db, device_id=d1.id, sales_batch_id=so.id)
    db.flush()
    rows = svc.list_sales_batch_devices(db, sales_batch_id=so.id)
    assert len([r for r in rows if r.active]) == 1
