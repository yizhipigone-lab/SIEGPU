"""预付款按月结转测试（二期 W9-10，D2 裁定：devices 字段单源，不建 prepayments 表）。

覆盖：直线月结转 golden / 计费钩子累加 / 全额结清置 settled（尾差收敛）/ 一期回租语义不变
（已置位不再动）/ 无预付款·无合同月数跳过 / 台账余额口径单一。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.device import Device, DeviceStage
from app.models.master import Customer, EquipmentModel
from app.models.project import Project
from app.services import billing_service as bsvc
from app.services import contract_service as csvc
from app.services import device_service as dsvc
from app.services import prepayment_service as svc


def _mk(db, *, prepayment=None, months: int | None = 12):
    """项目 + 客户 + 销售合同（可带起止）+ 点亮设备（可带预付款）。"""
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    kw = {}
    if months is not None:
        kw = {"start_date": date(2026, 1, 1), "end_date": date(2026, 1 + months - 1, 28)}
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=Decimal("1000000"), tax_rate=Decimal("0.13"), **kw)
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           monthly_price=Decimal("10000"), purchase_value=Decimal("960000"),
                           prepayment_amount=prepayment or Decimal("0"), ownership="表内自有")
    # 直接点亮（create_device 已自动建 7 行 → 置点亮行完成，不重复插行）
    d.status = "点亮验收"
    _st = db.query(DeviceStage).filter_by(device_id=d.id, stage="点亮验收").one()
    _st.status = "已完成"; _st.actual_date = date(2026, 1, 1)
    db.flush()
    return p, c, d


def _bill(db, d, c, period, billing_date):
    return bsvc.generate_billing_device(db, device_id=d.id, contract_id=c.id,
                                        period_index=period, billing_date=billing_date,
                                        created_by=None)


def test_monthly_settlement_golden(db):
    """直线法：12000/12 = 1000.00；1000/3 = 333.33。"""
    assert svc.monthly_settlement(Decimal("12000"), 12) == Decimal("1000.00")
    assert svc.monthly_settlement(Decimal("1000"), 3) == Decimal("333.33")


def test_settle_on_billing_accumulates(db):
    """计费钩子：每期计费结转 1000，累计 1000→2000；余额口径 = 总额 − 累计（单源）。"""
    p, c, d = _mk(db, prepayment=Decimal("12000"), months=12)
    amt1 = _bill(db, d, c, 1, date(2026, 1, 31))
    d = db.get(Device, d.id)
    assert d.prepayment_settled_amount == Decimal("1000.00") and d.prepayment_settled is False
    _bill(db, d, c, 2, date(2026, 2, 28))
    d = db.get(Device, d.id)
    assert d.prepayment_settled_amount == Decimal("2000.00")
    # 台账余额口径：12000 − 2000 = 10000
    rows = svc.prepayment_summary(db, project_id=p.id)
    assert rows[0]["remaining"] == Decimal("10000.00")


def test_full_settlement_sets_flag_with_remainder(db):
    """1000 分 3 个月：333.33 + 333.33 + 333.34（尾差收敛）→ 全额结清置 settled，累计精确 = 1000。"""
    p, c, d = _mk(db, prepayment=Decimal("1000"), months=3)
    _bill(db, d, c, 1, date(2026, 1, 31))
    assert db.get(Device, d.id).prepayment_settled_amount == Decimal("333.33")
    _bill(db, d, c, 2, date(2026, 2, 28))
    _bill(db, d, c, 3, date(2026, 3, 31))
    d = db.get(Device, d.id)
    assert d.prepayment_settled is True
    assert d.prepayment_settled_amount == Decimal("1000.00")  # 尾差收敛：结清即对齐总额
    # 结清后再计费不再结转
    _bill(db, d, c, 4, date(2026, 4, 30))
    assert db.get(Device, d.id).prepayment_settled_amount == Decimal("1000.00")


def test_skip_when_already_settled_leaseback_semantics(db):
    """一期售后回租语义不变：prepayment_settled 已置位（回租出售）→ 结转服务不再动该设备。"""
    p, c, d = _mk(db, prepayment=Decimal("12000"), months=12)
    d.prepayment_settled = True  # 模拟一期回租出售置位
    db.flush()
    assert _bill(db, d, c, 1, date(2026, 1, 31)) is not None  # 计费本身正常
    d = db.get(Device, d.id)
    assert d.prepayment_settled_amount is None  # 结转列没被碰（保持一期行为）


def test_skip_no_prepayment(db):
    p, c, d = _mk(db, prepayment=None, months=12)
    b = _bill(db, d, c, 1, date(2026, 1, 31))
    assert svc.settle_for_billing(db, b) is None
    assert db.get(Device, d.id).prepayment_settled_amount is None


def test_skip_missing_contract_dates(db):
    """合同月起止缺失 → 无规则依据，不结转（不静默乱结）。"""
    p, c, d = _mk(db, prepayment=Decimal("12000"), months=None)
    b = _bill(db, d, c, 1, date(2026, 1, 31))
    assert b is not None  # 计费不受阻
    assert db.get(Device, d.id).prepayment_settled_amount is None


def test_summary_aggregation(db):
    """台账聚合：两台设备一行一条，余额=总额−累计。"""
    p, c, d1 = _mk(db, prepayment=Decimal("12000"), months=12)
    e2 = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e2); db.flush()
    d2 = dsvc.create_device(db, project_id=p.id, equipment_model_id=e2.id,
                            purchase_value=Decimal("960000"), prepayment_amount=Decimal("6000"))
    _bill(db, d1, c, 1, date(2026, 1, 31))
    rows = svc.prepayment_summary(db)
    mine = {r["sn"]: r for r in rows}
    assert mine[d1.sn]["settled_amount"] == Decimal("1000.00")
    assert mine[d1.sn]["remaining"] == Decimal("11000.00")
    assert mine[d2.sn]["settled_amount"] == Decimal(0)
    assert mine[d2.sn]["settled"] is False


def test_device_prepayment_auto_ledger_with_date_and_supplier(db):
    """S3 缺陷#6：设备登记预付款自动落台账行，payment_date 取设备预付款日期，供应商取设备供应商。"""
    from app.models.master import Supplier
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    sup = Supplier(name="设备供应商B", type="设备供应商")
    db.add(sup); db.flush()
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id, supplier_id=sup.id,
                           prepayment_amount=Decimal("12000"), prepayment_date=date(2026, 2, 1))
    rows = svc.prepayment_summary(db, project_id=p.id)
    assert len(rows) == 1
    r = rows[0]
    assert r["sn"] == d.sn
    assert r["payment_date"] == "2026-02-01"
    assert r["supplier_name"] == "设备供应商B"
    assert r["prepayment_amount"] == Decimal("12000")
    assert r["settled"] is False
    assert r["remaining"] == Decimal("12000")


def test_settle_syncs_ledger_row(db):
    """S3：计费结转同时扣设备镜像字段与台账行 settled_amount（单源一致）。"""
    p, c, d = _mk(db, prepayment=Decimal("12000"), months=12)
    _bill(db, d, c, 1, date(2026, 1, 31))
    d = db.get(Device, d.id)
    assert d.prepayment_settled_amount == Decimal("1000.00")
    rows = svc.prepayment_summary(db, project_id=p.id)
    assert len(rows) == 1
    assert rows[0]["settled_amount"] == Decimal("1000.00")
    assert rows[0]["remaining"] == Decimal("11000.00")
    assert rows[0]["settled"] is False
