"""项目血缘树聚合测试：合同参照链 / 预付款状态口径 / 金租申请项目归属。"""
import uuid
from decimal import Decimal

from app.models.delivery import Order
from app.models.device import Device
from app.models.leasing import LeasingProcess
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Contract, Project
from app.models.sales_order import SalesOrder
from app.services import project_service as svc

D = Decimal


def _proj(db):
    p = Project(name=f"p{uuid.uuid4().hex[:6]}", status="进行中")
    db.add(p); db.flush(); return p


def _party(db):
    c = Customer(name=f"c{uuid.uuid4().hex[:6]}")
    s = Supplier(name=f"s{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add_all([c, s]); db.flush(); return c, s


def _em(db):
    em = EquipmentModel(name=f"em{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(em); db.flush(); return em


def _contract(db, proj, party_id, type_, parent=None, amount=D("1000")):
    c = Contract(project_id=proj.id, type=type_, party_type="customer" if type_ == "SALES" else "supplier",
                 party_id=party_id, direction="RECEIVABLE" if type_ == "SALES" else "PAYABLE",
                 amount=amount, contract_no=f"{type_}-{uuid.uuid4().hex[:6]}",
                 parent_contract_id=parent.id if parent else None, status="已签")
    db.add(c); db.flush(); return c


def _order(db, proj, contract=None, is_batch=False, batch_name=None):
    o = Order(project_id=proj.id, contract_id=contract.id if contract else None,
              is_batch=is_batch, batch_name=batch_name, status="已下单",
              quantity=2, total_amount=D("800"))
    db.add(o); db.flush(); return o


def _device(db, proj, em, order=None, batch=None, prepay=D("0"), settled_amt=None, settled=False):
    d = Device(sn=f"GPU-{uuid.uuid4().hex[:8]}", project_id=proj.id, equipment_model_id=em.id,
               order_id=order.id if order else None, batch_id=batch.id if batch else None,
               prepayment_amount=prepay, prepayment_settled_amount=settled_amt,
               prepayment_settled=settled)
    db.add(d); db.flush(); return d


def test_full_chain_tree(db):
    proj = _proj(db); cust, sup = _party(db); em = _em(db)
    sc = _contract(db, proj, cust.id, "SALES")
    pc = _contract(db, proj, sup.id, "PURCHASE", parent=sc)
    so = SalesOrder(project_id=proj.id, contract_id=sc.id, equipment_model_id=em.id,
                    quantity=2, monthly_rent_per_unit=D("100"), total_monthly_rent=D("200"))
    db.add(so); db.flush()
    po = _order(db, proj, contract=pc)
    _device(db, proj, em, order=po, prepay=D("300"))

    tree = svc.project_relationships(db, proj.id)
    assert tree["project"]["id"] == str(proj.id)
    assert len(tree["sales_contracts"]) == 1
    scn = tree["sales_contracts"][0]
    assert scn["contract_no"] == sc.contract_no and scn["party_name"] == cust.name
    assert [x["id"] for x in scn["sales_orders"]] == [str(so.id)]
    assert [x["id"] for x in scn["purchase_contracts"]] == [str(pc.id)]
    pcn = scn["purchase_contracts"][0]
    assert pcn["party_name"] == sup.name
    assert len(pcn["orders"]) == 1
    on = pcn["orders"][0]
    assert on["prepayment"]["status"] == "已付挂账"
    assert on["prepayment"]["total"] == 300.0 and on["prepayment"]["remaining"] == 300.0
    assert len(on["devices"]) == 1 and on["devices"][0]["sn"].startswith("GPU-")


def test_prepayment_status_transitions(db):
    proj = _proj(db); cust, sup = _party(db); em = _em(db)
    sc = _contract(db, proj, cust.id, "SALES")
    pc = _contract(db, proj, sup.id, "PURCHASE", parent=sc)
    po = _order(db, proj, contract=pc)
    # 无预付款
    _device(db, proj, em, order=po)
    tree = svc.project_relationships(db, proj.id)
    pp = tree["sales_contracts"][0]["purchase_contracts"][0]["orders"][0]["prepayment"]
    assert pp["status"] == "无预付款"
    # 部分核销
    d2 = _device(db, proj, em, order=po, prepay=D("100"), settled_amt=D("40"))
    tree = svc.project_relationships(db, proj.id)
    pp = tree["sales_contracts"][0]["purchase_contracts"][0]["orders"][0]["prepayment"]
    assert pp["status"] == "部分核销" and pp["remaining"] == 60.0
    # 全部核销 → 已回核销（把部分核销的设备结清）
    d2.prepayment_settled_amount = D("100"); d2.prepayment_settled = True; db.flush()
    tree = svc.project_relationships(db, proj.id)
    pp = tree["sales_contracts"][0]["purchase_contracts"][0]["orders"][0]["prepayment"]
    assert pp["status"] == "已回核销" and pp["remaining"] == 0.0


def test_prepayment_legacy_settled_flag_without_amount(db):
    """一期回租置位（settled=True 但 settled_amount 为 NULL）按全额已回核销计。"""
    proj = _proj(db); cust, sup = _party(db); em = _em(db)
    sc = _contract(db, proj, cust.id, "SALES")
    pc = _contract(db, proj, sup.id, "PURCHASE", parent=sc)
    po = _order(db, proj, contract=pc)
    _device(db, proj, em, order=po, prepay=D("200"), settled_amt=None, settled=True)
    tree = svc.project_relationships(db, proj.id)
    pp = tree["sales_contracts"][0]["purchase_contracts"][0]["orders"][0]["prepayment"]
    assert pp["status"] == "已回核销" and pp["settled"] == 200.0


def test_leasing_linked_to_project(db):
    proj = _proj(db); other = _proj(db); cust, sup = _party(db)
    lp = LeasingProcess(project_id=proj.id, supplier_id=sup.id, total_amount=D("5000"),
                        financing_type="金租直租", status="进行中")
    db.add(lp); db.flush()
    lp2 = LeasingProcess(project_id=other.id, supplier_id=sup.id, total_amount=D("999"),
                         financing_type="银行流贷", status="进行中")
    db.add(lp2); db.flush()
    tree = svc.project_relationships(db, proj.id)
    assert [x["id"] for x in tree["leasing_processes"]] == [str(lp.id)]
    assert tree["leasing_processes"][0]["financing_type"] == "金租直租"
    assert tree["leasing_processes"][0]["supplier_name"] == sup.name


def test_orphans_and_unlinked_orders(db):
    proj = _proj(db); cust, sup = _party(db)
    # 历史孤儿采购合同（无参照）与未挂合同的批次订单不丢失
    pc_orphan = _contract(db, proj, sup.id, "PURCHASE", parent=None)
    batch = _order(db, proj, contract=None, is_batch=True, batch_name="批次A")
    tree = svc.project_relationships(db, proj.id)
    assert [x["id"] for x in tree["orphan_purchase_contracts"]] == [str(pc_orphan.id)]
    assert [x["id"] for x in tree["unlinked_orders"]] == [str(batch.id)]
    assert tree["unlinked_orders"][0]["label"] == "批次A"
    assert tree["sales_contracts"] == []


def test_project_not_found_returns_none(db):
    assert svc.project_relationships(db, uuid.uuid4()) is None