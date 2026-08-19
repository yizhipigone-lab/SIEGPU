"""采购合同参照销售合同：强制参照 + 总额硬校验。"""
import uuid
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.master import Customer, Supplier
from app.models.project import Contract, Project
from app.services import contract_service as svc


def _proj(db):
    p = Project(name=f"p{uuid.uuid4().hex[:6]}", status="进行中")
    db.add(p); db.flush()
    return p


def _party(db):
    c = Customer(name=f"c{uuid.uuid4().hex[:6]}")
    s = Supplier(name=f"s{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add_all([c, s]); db.flush()
    return c, s


def _sales(db, proj, cust, incl=Decimal("1000")):
    return svc.create_contract(db, project_id=proj.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"), amount_incl_tax=incl)


def test_purchase_requires_sales_parent(db):
    proj = _proj(db); cust, sup = _party(db)
    with pytest.raises(BusinessError) as e:
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("100"), tax_rate=Decimal("0.13"), amount_incl_tax=Decimal("110"))
    assert "参照" in str(e.value)


def test_parent_must_be_same_project_sales(db):
    proj = _proj(db); cust, sup = _party(db)
    other = _proj(db)
    sales_other = svc.create_contract(db, project_id=other.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"), amount_incl_tax=Decimal("1000"))
    with pytest.raises(BusinessError):
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("100"), tax_rate=Decimal("0.13"),
            amount_incl_tax=Decimal("110"), parent_contract_id=sales_other.id)


def test_purchase_total_capped_by_sales(db):
    proj = _proj(db); cust, sup = _party(db)
    sales = _sales(db, proj, cust, incl=Decimal("1000"))
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("500"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("600"), parent_contract_id=sales.id)
    with pytest.raises(BusinessError) as e:
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("500"), tax_rate=Decimal("0.13"),
            amount_incl_tax=Decimal("500"), parent_contract_id=sales.id)
    assert "额度" in str(e.value) or "超过" in str(e.value)


def test_purchase_total_fallback_to_net_amount(db):
    """销售合同无含税金额时退回不含税口径对比。"""
    proj = _proj(db); cust, sup = _party(db)
    sales = svc.create_contract(db, project_id=proj.id, type="SALES", party_id=cust.id,
        amount=Decimal("1000"), tax_rate=Decimal("0.13"), amount_incl_tax=None)
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("800"), tax_rate=Decimal("0.13"),
        amount_incl_tax=None, parent_contract_id=sales.id)
    with pytest.raises(BusinessError):
        svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
            amount=Decimal("300"), tax_rate=Decimal("0.13"),
            amount_incl_tax=None, parent_contract_id=sales.id)


def test_update_sales_returns_reference_count(db):
    proj = _proj(db); cust, sup = _party(db)
    sales = _sales(db, proj, cust, incl=Decimal("1000"))
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("100"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("110"), parent_contract_id=sales.id)
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("200"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("220"), parent_contract_id=sales.id)
    updated = svc.update_contract(db, sales.id, amount_incl_tax=Decimal("1500"))
    assert getattr(updated, "referenced_purchase_count", None) == 2


def test_list_by_parent_and_parent_no(db):
    proj = _proj(db); cust, sup = _party(db)
    sales = svc.create_contract(db, project_id=proj.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("1000"), contract_no="S-1")
    svc.create_contract(db, project_id=proj.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("100"), tax_rate=Decimal("0.13"),
        amount_incl_tax=Decimal("110"), parent_contract_id=sales.id)
    children = svc.list_contracts(db, parent_contract_id=sales.id)
    assert len(children) == 1
    assert getattr(children[0], "parent_contract_no", None) == "S-1"
