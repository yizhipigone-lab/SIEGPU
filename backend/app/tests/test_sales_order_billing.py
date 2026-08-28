"""S5（缺陷#14/#15/#17）：按销售订单出计费单——批内设备汇总一张单、未点亮拦截、防双计、dup-check。"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.device import Device, DeviceStage
from app.models.master import Customer, EquipmentModel
from app.models.project import Project
from app.services import billing_service as bsvc
from app.services import contract_service as csvc
from app.services import device_service as dsvc
from app.services import sales_order_service as sosvc


def _mk(db, *, n_dev=2):
    """项目 + 客户 + 销售合同（monthly_rent 10000）+ 设备型号 + 销售批次（挂 n 台点亮设备）。"""
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=Decimal("1000000"), tax_rate=Decimal("0.13"),
                             start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
                             monthly_rent=Decimal("10000"))
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    so = sosvc.create_sales_order(db, project_id=p.id, contract_id=c.id, equipment_model_id=e.id,
                                  quantity=n_dev, monthly_rent_per_unit=Decimal("10000"),
                                  total_monthly_rent=Decimal(10000 * n_dev),
                                  is_batch=True, batch_name=f"B-{uuid.uuid4().hex[:6]}")
    devs = []
    for i in range(n_dev):
        d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                               monthly_price=Decimal("10000"), purchase_value=Decimal("960000"),
                               ownership="表内自有")
        d.status = "点亮验收"
        # 缺陷#16：create_device 自动建 7 行 → 把自动建的点亮行置完成（不重复插行）
        _st = db.query(DeviceStage).filter_by(device_id=d.id, stage="点亮验收").one()
        _st.status = "已完成"; _st.actual_date = date(2026, 1, 1)
        db.flush()
        sosvc.add_to_sales_batch(db, device_id=d.id, sales_batch_id=so.id, operator_id=None)
        devs.append(d)
    return p, c, so, devs


def test_sales_order_billing_summarizes_devices(db):
    """缺陷#14/#15：按销售订单出一张汇总计费单，金额=Σ设备月租×期比例，sales_order_id 落单。"""
    p, c, so, devs = _mk(db, n_dev=2)
    b = bsvc.generate_billing_sales_order(db, sales_order_id=so.id, period_index=1,
                                          billing_date=date(2026, 1, 31), created_by=None)
    assert b.sales_order_id == so.id
    assert b.device_id is None  # 汇总单不挂单台
    # 首月按剩余天数比例：1/1 点亮 → 1 月 31 天全计 → 单台 10000，两台 20000
    assert b.amount == Decimal("20000.00")
    assert b.amount_ex_tax == pytest.approx(Decimal("20000") / Decimal("1.13"), abs=0.01)


def test_sales_order_billing_unlit_device_blocked(db):
    """缺陷#16：批内设备未点亮验收 → 拦截并提示。"""
    p, c, so, devs = _mk(db, n_dev=1)
    d = devs[0]
    d.status = "上架"  # 模拟未点亮
    st = db.execute(__import__("sqlalchemy").select(DeviceStage).where(
        DeviceStage.device_id == d.id, DeviceStage.stage == "点亮验收")).scalar_one()
    st.status = "进行中"
    db.flush()
    with pytest.raises(BusinessError) as exc:
        bsvc.generate_billing_sales_order(db, sales_order_id=so.id, period_index=1,
                                          billing_date=date(2026, 1, 31), created_by=None)
    assert "点亮" in str(exc.value.detail)


def test_sales_order_billing_dup_check(db):
    """K1：同销售订单同期只能出一张汇总单（服务层 dup-check，不建 DB 索引）。"""
    p, c, so, devs = _mk(db, n_dev=1)
    bsvc.generate_billing_sales_order(db, sales_order_id=so.id, period_index=1,
                                      billing_date=date(2026, 1, 31), created_by=None)
    with pytest.raises(BusinessError) as exc:
        bsvc.generate_billing_sales_order(db, sales_order_id=so.id, period_index=1,
                                          billing_date=date(2026, 1, 31), created_by=None)
    assert "已计费" in str(exc.value.detail)


def test_sales_order_billing_skips_already_billed_device(db):
    """K4③：批内设备该期已按台计费 → 汇总时跳过；全部已计费 → 拦。"""
    p, c, so, devs = _mk(db, n_dev=2)
    # 第 1 台先按台计费
    bsvc.generate_billing_device(db, device_id=devs[0].id, contract_id=c.id, period_index=1,
                                 billing_date=date(2026, 1, 31), created_by=None)
    # 汇总单只含第 2 台 → 10000
    b = bsvc.generate_billing_sales_order(db, sales_order_id=so.id, period_index=1,
                                          billing_date=date(2026, 1, 31), created_by=None)
    assert b.amount == Decimal("10000.00")
    # 第 2 台也按台计费后，再汇总 → 拦
    bsvc.generate_billing_device(db, device_id=devs[1].id, contract_id=c.id, period_index=1,
                                 billing_date=date(2026, 1, 31), created_by=None)
    with pytest.raises(BusinessError):
        bsvc.generate_billing_sales_order(db, sales_order_id=so.id, period_index=1,
                                          billing_date=date(2026, 1, 31), created_by=None)
