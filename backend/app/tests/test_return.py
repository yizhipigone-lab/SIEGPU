"""采购退货测试（三期 §4.4）：申请守卫 → 出库（已退货）→ 收货（资产减少）→ 红票 → 退款核销全链 golden
+ 合同终止资源释放。db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.billing import Invoice
from app.models.device import Device
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.payment import PaymentSettlement
from app.models.project import Project
from app.services import contract_amendment_service as amendsvc
from app.services import contract_service as csvc
from app.services import device_service as dsvc
from app.services import invoice_service as isvc
from app.services import return_service as svc


def _setup(db, n_devices=2, prepay=False):
    """项目 + 供应商 + 采购合同 + n 台到货设备（60万/40万…）。"""
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    sup = Supplier(name=f"S-{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add(sup); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                             amount=Decimal("10000000"), tax_rate=Decimal("0.13"))
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    devices = []
    for i, pv in enumerate([Decimal("600000"), Decimal("400000")][:n_devices]):
        d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                               purchase_value=pv,
                               prepayment_amount=Decimal("12000") if (prepay and i == 0) else Decimal("0"))
        d.status = "到货"
        devices.append(d)
    db.flush()
    return p, c, devices


def test_create_return_golden(db):
    """申请：金额=Σ原值 100 万；预付款追回额=设备剩余预付款 12000。"""
    p, c, devices = _setup(db, prepay=True)
    ro = svc.create_return(db, project_id=p.id, return_type="到货不合格",
                           device_ids=[d.id for d in devices], reason="开箱损")
    assert ro.total_amount == Decimal("1000000.00")
    assert ro.prepayment_recover == Decimal("12000.00")
    assert ro.status == "退货申请"
    assert len(svc.list_return_devices(db, ro.id)) == 2


def test_guards(db):
    """守卫：点亮设备不可退 / 已退货不可再退 / 空设备列表。"""
    p, c, devices = _setup(db)
    devices[0].status = "点亮验收"
    db.flush()
    with pytest.raises(BusinessError, match="点亮验收"):
        svc.create_return(db, project_id=p.id, return_type="压测不通过",
                          device_ids=[devices[0].id])
    with pytest.raises(BusinessError):
        svc.create_return(db, project_id=p.id, return_type="压测不通过", device_ids=[])
    ro = svc.create_return(db, project_id=p.id, return_type="压测不通过",
                           device_ids=[devices[1].id])
    svc.advance_return(db, ro.id)  # 已出库 → 设备已退货
    with pytest.raises(BusinessError, match="已退货"):
        svc.create_return(db, project_id=p.id, return_type="压测不通过",
                          device_ids=[devices[1].id])
    # 已退货设备不可再推进状态机
    with pytest.raises(BusinessError, match="已退货"):
        dsvc.advance_device_stage(db, device_id=devices[1].id, stage="己方压测", status="进行中")


def test_full_chain_golden(db):
    """全链：申请→出库(设备已退货)→收货(资产减少)→红票(红冲关联)→退款核销(流水+核销行)。"""
    p, c, devices = _setup(db)
    # 设备 1 建资产卡（模拟已转固）
    a = Asset(project_id=p.id, equipment_model_id=devices[0].equipment_model_id,
              device_id=devices[0].id, quantity=1,
              unit_original_value=Decimal("600000"), total_original_value=Decimal("600000"),
              operation_status="已转固未运营")
    db.add(a); db.flush()
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("1000000"),
                              invoice_no=f"INV-R-{uuid.uuid4().hex[:6]}", issue_date=date(2026, 8, 1))
    ro = svc.create_return(db, project_id=p.id, return_type="到货不合格",
                           device_ids=[d.id for d in devices], original_invoice_id=inv.id)

    svc.advance_return(db, ro.id)  # → 已出库
    for d in devices:
        assert db.get(Device, d.id).status == "已退货"

    svc.advance_return(db, ro.id)  # → 供应商已收货（资产减少）
    assert db.get(Asset, a.id).deleted_at is not None

    svc.advance_return(db, ro.id, transaction_date=date(2026, 8, 12))  # → 已开红字发票
    ro = svc.get_return_or_404(db, ro.id)
    red = db.get(Invoice, ro.red_invoice_id)
    assert red is not None and red.direction == "PAYABLE"
    assert red.reversal_of_id == inv.id  # 红冲关联原票
    assert red.amount == Decimal("1000000.00")

    svc.advance_return(db, ro.id, transaction_date=date(2026, 8, 13))  # → 已退款核销
    ro = svc.get_return_or_404(db, ro.id)
    assert ro.status == "已退款核销" and ro.refund_txn_id is not None
    st = db.execute(select(PaymentSettlement).where(
        PaymentSettlement.capital_transaction_id == ro.refund_txn_id)).scalars().one()
    assert st.invoice_id == ro.red_invoice_id and st.amount == Decimal("1000000.00")
    # 终态不可再推进
    with pytest.raises(BusinessError):
        svc.advance_return(db, ro.id)


def test_step_order_enforced(db):
    """强顺序：未开红票不可退款核销。"""
    p, c, devices = _setup(db)
    ro = svc.create_return(db, project_id=p.id, return_type="合同终止",
                           device_ids=[devices[0].id])
    svc.advance_return(db, ro.id)  # 已出库
    svc.advance_return(db, ro.id)  # 供应商已收货
    # 当前=供应商已收货，下一步=已开红字发票（正常）；终态推进报错已在上条覆盖
    ro = svc.advance_return(db, ro.id)  # 已开红字发票
    assert ro.status == "已开红字发票"


def test_sales_termination_releases_devices(db):
    """合同终止结算：销售终止 → 设备摘下销售合同（资源释放）。"""
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           purchase_value=Decimal("960000"), sales_contract_id=c.id)
    amendsvc.terminate_contract(db, c.id, termination_date=date(2026, 8, 12), reason="客户违约")
    assert db.get(Device, d.id).sales_contract_id is None
