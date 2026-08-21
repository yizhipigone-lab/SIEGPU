"""销售验收「上架」同步测试（W4）。"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.delivery import DeliveryStage
from app.models.device import Device
from app.models.master import Customer, EquipmentModel
from app.models.project import Contract, Project
from app.services import acceptance_service as acc
from app.services import device_service as dsvc
from app.services import order_service as osvc
from app.services import sales_order_service as so_svc

D = Decimal


def _mk_project(db, code):
    cust = Customer(name=f"客户-{code}", industry="测试")
    db.add(cust); db.flush()
    eq = EquipmentModel(name=f"卡-{code}", category="大卡", gpu_type="A100")
    db.add(eq); db.flush()
    p = Project(name=f"项目-{code}", code=code, total_investment=D("100000"))
    db.add(p); db.flush()
    sc = Contract(project_id=p.id, type="SALES", party_type="customer", party_id=cust.id,
                  direction="RECEIVABLE", amount=D("100000"), tax_rate=D("0.06"))
    db.add(sc); db.flush()
    return p, eq, sc


def test_sales_acceptance_shelve_completes_device_stage(db):
    """销售验收勾上架（销售批次路径）→ 批内设备 device_stages 上架→已完成。"""
    p, eq, sc = _mk_project(db, "SHELVE-DEV")
    so = so_svc.create_sales_order(db, project_id=p.id, contract_id=sc.id,
                                   equipment_model_id=eq.id, quantity=1,
                                   monthly_rent_per_unit=D("1000"), total_monthly_rent=D("1000"),
                                   is_batch=True, batch_name="销售批次1")
    d = Device(project_id=p.id, equipment_model_id=eq.id, sn="GPU-SHELVE-01",
               purchase_value=D("10000"), leasing_mode="自有", ownership="表内自有")
    db.add(d); db.flush()
    so_svc.add_to_sales_batch(db, device_id=d.id, sales_batch_id=so.id)
    d.status = "到货"  # 四期 W4 期3 硬流转#2：销售验收前设备须已发货（在途/到货…）
    db.flush()
    ar = acc.create_acceptance(db, project_id=p.id, acceptance_type="销售验收",
                               sales_order_id=so.id, quantity_accepted=1, shelve=True)
    db.flush()
    acc.approve_acceptance(db, ar, acceptance_date=date(2026, 6, 28))
    db.flush()
    stages = dsvc.list_device_stages(db, d.id)
    shelve_row = next(s for s in stages if s.stage == "上架")
    assert shelve_row.status == "已完成"


def test_sales_acceptance_no_shelve_does_nothing(db):
    """未勾选上架 → 不推进任何上架节点。"""
    p, eq, sc = _mk_project(db, "SHELVE-NO")
    so = so_svc.create_sales_order(db, project_id=p.id, contract_id=sc.id,
                                   equipment_model_id=eq.id, quantity=1,
                                   monthly_rent_per_unit=D("1000"), total_monthly_rent=D("1000"),
                                   is_batch=True, batch_name="销售批次1")
    d = Device(project_id=p.id, equipment_model_id=eq.id, sn="GPU-SHELVE-02",
               purchase_value=D("10000"), leasing_mode="自有", ownership="表内自有")
    db.add(d); db.flush()
    so_svc.add_to_sales_batch(db, device_id=d.id, sales_batch_id=so.id)
    d.status = "到货"  # 期3 硬流转#2：设备须已发货
    db.flush()
    ar = acc.create_acceptance(db, project_id=p.id, acceptance_type="销售验收",
                               sales_order_id=so.id, quantity_accepted=1, shelve=False)
    db.flush()
    acc.approve_acceptance(db, ar, acceptance_date=date(2026, 6, 28))
    db.flush()
    stages = dsvc.list_device_stages(db, d.id)
    shelve_row = next((s for s in stages if s.stage == "上架"), None)
    # 未勾选上架 → 不推进，节点行不存在或非已完成
    assert shelve_row is None or shelve_row.status != "已完成"


def test_sales_acceptance_shelve_completes_legacy_stage(db):
    """销售验收勾上架（旧6阶段路径）→ 同项目采购订单 delivery_stages 上架→已完成。"""
    p, eq, sc = _mk_project(db, "SHELVE-LEG")
    so = so_svc.create_sales_order(db, project_id=p.id, contract_id=sc.id,
                                   equipment_model_id=eq.id, quantity=1,
                                   monthly_rent_per_unit=D("1000"), total_monthly_rent=D("1000"))
    po = osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id,
                           quantity=1, unit_price=D("10000"))
    db.flush()
    ar = acc.create_acceptance(db, project_id=p.id, acceptance_type="销售验收",
                               sales_order_id=so.id, quantity_accepted=1, shelve=True)
    db.flush()
    acc.approve_acceptance(db, ar, acceptance_date=date(2026, 6, 28))
    db.flush()
    stage = db.execute(select(DeliveryStage).where(
        DeliveryStage.order_id == po.id, DeliveryStage.stage == "上架"
    )).scalar_one()
    assert stage.status == "已完成"
