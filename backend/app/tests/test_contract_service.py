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


def test_contract_biz_type_incl_tax_lease_months(db):
    """四期 W4：合同类型/含税总额/租期可创建并持久化。"""
    p = _project(db)
    cust = Customer(name="客户B"); db.add(cust); db.flush()
    c = svc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                            amount=Decimal("10000000"), tax_rate=Decimal("0.13"),
                            biz_type="算力租赁", amount_incl_tax=Decimal("11300000"), lease_months=36)
    assert c.biz_type == "算力租赁"
    assert c.amount_incl_tax == Decimal("11300000")
    assert c.lease_months == 36
    assert c.amount == Decimal("10000000")  # 不含税口径不变


def test_update_contract_amount_persists(db):
    """回归：编辑时「不含税金额」必须能保存（此前 amount 不在更新白名单，保存后被丢弃、刷新还原）。"""
    p = _project(db)
    cust = Customer(name="客户C"); db.add(cust); db.flush()
    c = svc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                            amount=Decimal("10000000"), tax_rate=Decimal("0.13"),
                            amount_incl_tax=Decimal("11300000"))
    # 改含税 → 不含税联动（前端算好后随 PATCH 一起提交，两者都应落库）
    svc.update_contract(db, c.id, amount_incl_tax=Decimal("22600000"), amount=Decimal("20000000"))
    assert c.amount_incl_tax == Decimal("22600000")
    assert c.amount == Decimal("20000000")  # 不含税金额保存成功（不再还原成旧值）
