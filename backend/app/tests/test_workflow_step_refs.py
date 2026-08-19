"""workflow steps 附带对应实体 id（步骤导航跳转用）。"""
import uuid
from decimal import Decimal

from app.models.master import Customer, Supplier
from app.models.project import Project
from app.services import contract_service as con_svc
from app.services import workflow_service as wf_svc


def test_steps_carry_entity_ids(db):
    p = Project(name=f"p{uuid.uuid4().hex[:6]}", status="进行中")
    db.add(p); db.flush()
    wf_svc.create_workflow(db, project_id=p.id)
    cust = Customer(name=f"c{uuid.uuid4().hex[:6]}")
    sup = Supplier(name=f"s{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add_all([cust, sup]); db.flush()
    sales = con_svc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
        amount=Decimal("900"), tax_rate=Decimal("0.13"), amount_incl_tax=Decimal("1000"))
    purchase = con_svc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
        amount=Decimal("800"), tax_rate=Decimal("0.13"), amount_incl_tax=Decimal("900"),
        parent_contract_id=sales.id)
    wf = wf_svc.get_workflow(db, p.id)
    steps = {s.get("name"): s for s in wf.steps}
    # 步骤导航：销售/采购合同步骤携带实体 id + 数量，前端深链跳转
    assert steps["销售合同"].get("sales_contract_id") == str(sales.id)
    assert steps["销售合同"].get("sales_contract_count") == 1
    assert steps["采购合同"].get("purchase_contract_id") == str(purchase.id)
    assert steps["采购合同"].get("purchase_contract_count") == 1
    # 无实体的步骤不挂引用
    assert steps["项目建立"].get("sales_contract_id") is None
