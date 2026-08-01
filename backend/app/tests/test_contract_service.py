"""合同服务测试：type 决定 direction/party_type；party 类型校验。"""
import uuid
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.master import Customer, Supplier
from app.models.project import Project
from app.services import contract_service as svc


def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def test_sales_contract_direction_and_party(db):
    p = _project(db)
    cust = Customer(name="客户A"); db.add(cust); db.flush()
    c = svc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                            amount=Decimal("1000000"), tax_rate=Decimal("0.13"),
                            monthly_rent=Decimal("100000"))
    assert c.direction == "RECEIVABLE" and c.party_type == "customer"
    assert c.status == "已签"


def test_purchase_contract(db):
    p = _project(db)
    sup = Supplier(name="供应商A", type="设备供应商"); db.add(sup); db.flush()
    c = svc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                            amount=Decimal("500000"), tax_rate=Decimal("0.13"))
    assert c.direction == "PAYABLE" and c.party_type == "supplier"


def test_sales_party_must_be_customer(db):
    p = _project(db)
    sup = Supplier(name="供应商A", type="设备供应商"); db.add(sup); db.flush()
    with pytest.raises(BusinessError):  # party 是供应商却建销售合同
        svc.create_contract(db, project_id=p.id, type="SALES", party_id=sup.id, amount=Decimal("1"), tax_rate=Decimal("0.13"))


def test_bad_project(db):
    cust = Customer(name="c"); db.add(cust); db.flush()
    with pytest.raises(BusinessError):
        svc.create_contract(db, project_id=uuid.uuid4(), type="SALES", party_id=cust.id, amount=Decimal("1"), tax_rate=Decimal("0.13"))
