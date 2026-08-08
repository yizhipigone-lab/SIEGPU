"""W7-8 集成测试：售后回租·回租出售全链路（Phase 3）。

覆盖 create_leaseback_sale 6 步 + Step 0 守门 6 分支（spec §2.4 回租出售切已处置+表外+长期应付款）。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.device import OffBalanceRegister
from app.models.long_term_payable import LongTermPayable
from app.models.master import EquipmentModel, Supplier
from app.models.project import Project
from app.services import device_service as dsvc
from app.services import leasing_service as lsvc
from app.services import leaseback_sale_service as lbsvc


# ---- helpers ----

def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8)
    db.add(e); db.flush(); return e


def _funding_supplier(db, name="某金租", type_="资金供应商"):
    s = Supplier(name=name, type=type_, is_leasing_org=(type_ == "资金供应商"))
    db.add(s); db.flush(); return s


def _leasing_process(db, project_id, supplier_id, total=Decimal("1000000")):
    return lsvc.create_process(db, project_id=project_id, supplier_id=supplier_id,
                               total_amount=total, leasing_mode="售后回租",
                               financing_type="金租回租")


def _advance_to(db, device_id, target_stage, light_on_date=None):
    """推进到 target_stage；点亮验收需传 light_on_date 才激活起折旧。"""
    for st in dsvc.DEVICE_STAGES[:dsvc.DEVICE_STAGES.index(target_stage) + 1]:
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="进行中")
        kw = {"stage": st, "status": "已完成"}
        if st == "点亮验收" and light_on_date is not None:
            kw["actual_date"] = light_on_date
        dsvc.advance_device_stage(db, device_id=device_id, **kw)


def _asset_of(db, device_id):
    return db.execute(select(Asset).where(Asset.device_id == device_id)).scalar_one()


def _err_code(exc_info):
    return exc_info.value.detail["code"]


# ---- 全链路 ----

def test_full_chain_lit_asset_truncates_and_settles(db):
    """运营中资产回租出售：折旧截断 + 已处置 + off_balance(售后回租) + LTP + settled。"""
    p = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "点亮验收", light_on_date=date(2026, 1, 15))
    proc = _leasing_process(db, p.id, sup.id)

    res = lbsvc.create_leaseback_sale(
        db, device_id=d.id, sale_date=date(2026, 3, 20), leasing_org_id=sup.id,
        sale_price=Decimal("950000"), leasing_process_id=proc.id, operator_id=None)

    a = _asset_of(db, d.id)
    assert a.operation_status == "已处置"
    assert a.end_date == date(2026, 3, 20)          # 折旧截断到出售日
    assert a.monthly_depreciation == Decimal("14400.00")  # 原值保留不动
    # Step 2 off_balance
    reg = db.execute(select(OffBalanceRegister).where(
        OffBalanceRegister.device_id == d.id)).scalar_one()
    assert reg.register_type == "售后回租"
    # Step 3 LongTermPayable
    ltp = db.execute(select(LongTermPayable).where(
        LongTermPayable.device_id == d.id)).scalar_one()
    assert ltp.principal_amount == Decimal("950000")
    assert ltp.status == "已确认"
    assert ltp.confirm_date == date(2026, 3, 20)
    # 返回值 + Step 4 settled
    assert res["sale_gain_loss"] == Decimal("18800.00")
    db.refresh(d)
    assert d.prepayment_settled is True


# ---- Step 0 守门 6 分支 ----

def test_reject_non_leaseback_mode(db):
    """非售后回租设备 → 400 BAD_REQUEST（第一道守门）。"""
    p = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="直租", purchase_value=Decimal("960000"))
    proc = _leasing_process(db, p.id, sup.id)
    with pytest.raises(BusinessError) as ei:
        lbsvc.create_leaseback_sale(db, device_id=d.id, sale_date=date(2026, 3, 20),
                                    leasing_org_id=sup.id, sale_price=Decimal("900000"),
                                    leasing_process_id=proc.id)
    assert ei.value.status_code == 400
    assert _err_code(ei) == "BAD_REQUEST"


def test_reject_off_balance_ownership(db):
    """售后回租但显式表外 → 409 STATE_ERROR（ownership 守门，非第一道）。"""
    p = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", ownership="金租表外",  # 显式表外
                           purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "上架")  # 上架建 off_balance，不建资产卡
    proc = _leasing_process(db, p.id, sup.id)
    with pytest.raises(BusinessError) as ei:
        lbsvc.create_leaseback_sale(db, device_id=d.id, sale_date=date(2026, 3, 20),
                                    leasing_org_id=sup.id, sale_price=Decimal("900000"),
                                    leasing_process_id=proc.id)
    assert ei.value.status_code == 409
    assert _err_code(ei) == "STATE_ERROR"


def test_reject_no_asset_card(db):
    """售后回租表内但未上架（无资产卡）→ 409 STATE_ERROR。"""
    p = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))
    # ownership 派生在 上架 才发生；未上架 ownership 仍 None → 撞 ownership 守门（STATE_ERROR）
    proc = _leasing_process(db, p.id, sup.id)
    with pytest.raises(BusinessError) as ei:
        lbsvc.create_leaseback_sale(db, device_id=d.id, sale_date=date(2026, 3, 20),
                                    leasing_org_id=sup.id, sale_price=Decimal("900000"),
                                    leasing_process_id=proc.id)
    assert ei.value.status_code == 409


def test_reject_double_sale_idempotent(db):
    """已处置资产再次出售 → 409 DUPLICATE（幂等主守门）。"""
    p = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "点亮验收", light_on_date=date(2026, 1, 15))
    proc = _leasing_process(db, p.id, sup.id)
    lbsvc.create_leaseback_sale(db, device_id=d.id, sale_date=date(2026, 3, 20),
                                leasing_org_id=sup.id, sale_price=Decimal("950000"),
                                leasing_process_id=proc.id)
    with pytest.raises(BusinessError) as ei:  # 二售
        lbsvc.create_leaseback_sale(db, device_id=d.id, sale_date=date(2026, 4, 1),
                                    leasing_org_id=sup.id, sale_price=Decimal("940000"),
                                    leasing_process_id=proc.id)
    assert ei.value.status_code == 409
    assert _err_code(ei) == "DUPLICATE"


def test_reject_wrong_supplier_type(db):
    """金租机构 type != 资金供应商 → 400 BAD_REQUEST。"""
    p = _project(db); e = _equipment(db)
    sup = _funding_supplier(db, name="设备商", type_="设备供应商")  # 非金租
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "点亮验收", light_on_date=date(2026, 1, 15))
    # 用真金秛建 leasing_process（create_process 自身要校验）
    real_sup = _funding_supplier(db, name="真金租")
    proc = _leasing_process(db, p.id, real_sup.id)
    with pytest.raises(BusinessError) as ei:
        lbsvc.create_leaseback_sale(db, device_id=d.id, sale_date=date(2026, 3, 20),
                                    leasing_org_id=sup.id, sale_price=Decimal("900000"),
                                    leasing_process_id=proc.id)
    assert ei.value.status_code == 400


def test_reject_process_other_project(db):
    """leasing_process 与设备不属于同一项目 → 400 BAD_REQUEST。"""
    p1 = _project(db); p2 = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p1.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "点亮验收", light_on_date=date(2026, 1, 15))
    proc = _leasing_process(db, p2.id, sup.id)  # 另一个项目
    with pytest.raises(BusinessError) as ei:
        lbsvc.create_leaseback_sale(db, device_id=d.id, sale_date=date(2026, 3, 20),
                                    leasing_org_id=sup.id, sale_price=Decimal("900000"),
                                    leasing_process_id=proc.id)
    assert ei.value.status_code == 400


# ---- 计算 / 状态 ----

def test_sale_gain_loss_gain_and_loss(db):
    """sale_gain_loss 收益/损失/平三态（sale_price vs carrying）。"""
    p = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "点亮验收", light_on_date=date(2026, 1, 15))  # 月折旧 14400
    proc = _leasing_process(db, p.id, sup.id)
    # carrying after 2 months = 931200
    res_gain = lbsvc.create_leaseback_sale(
        db, device_id=d.id, sale_date=date(2026, 3, 20), leasing_org_id=sup.id,
        sale_price=Decimal("950000"), leasing_process_id=proc.id)
    assert res_gain["sale_gain_loss"] == Decimal("18800.00")
    assert res_gain["carrying_amount"] == Decimal("931200.00")


def test_activated_not_operating_sale_carries_original(db):
    """已转固未运营（未起折旧）出售 → carrying = 原值 960000，gain = 售价 - 原值。"""
    p = _project(db); e = _equipment(db); sup = _funding_supplier(db)
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           leasing_mode="售后回租", purchase_value=Decimal("960000"))
    _advance_to(db, d.id, "上架")  # 只到上架：已转固未运营，不起折旧
    proc = _leasing_process(db, p.id, sup.id)
    res = lbsvc.create_leaseback_sale(
        db, device_id=d.id, sale_date=date(2026, 3, 20), leasing_org_id=sup.id,
        sale_price=Decimal("1000000"), leasing_process_id=proc.id)
    assert res["carrying_amount"] == Decimal("960000")
    assert res["sale_gain_loss"] == Decimal("40000.00")
    a = _asset_of(db, d.id)
    assert a.operation_status == "已处置"
