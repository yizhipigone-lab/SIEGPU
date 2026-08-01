"""订单/交付测试：6 阶段、状态机、点亮→资产+折旧（W20）、幂等。"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.master import EquipmentModel
from app.models.project import Project
from app.services import order_service as svc


def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8); db.add(e); db.flush(); return e


def test_create_order_generates_6_stages(db):
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=10, unit_price=Decimal("100000"))
    assert o.total_amount == Decimal("1000000")
    _, stages = svc.get_order_with_stages(db, o.id)
    assert [s.stage for s in stages] == ["订货", "到货", "压测", "运输在途", "上架", "点亮"]
    assert all(s.status == "未开始" for s in stages)


def test_stage_illegal_transition(db):
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=1, unit_price=Decimal("1"))
    _, stages = svc.get_order_with_stages(db, o.id)
    with pytest.raises(BusinessError):  # 未开始 → 已完成 非法
        svc.advance_stage(db, stage_id=stages[0].id, status="已完成")
    svc.advance_stage(db, stage_id=stages[0].id, status="进行中")
    svc.advance_stage(db, stage_id=stages[0].id, status="已完成", actual_date=date(2026, 6, 1))


def test_light_on_generates_asset_and_depreciation(db):
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=10, unit_price=Decimal("100000"))
    o2, asset = svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    assert o2.status == "已点亮"
    assert asset.start_date == date(2026, 9, 15)
    assert asset.monthly_depreciation == Decimal("15000.00")  # 1,000,000 × 0.9 / 60
    assert asset.end_date == date(2031, 9, 15)  # +5 年（add_months 60）
    assets = db.execute(select(Asset).where(Asset.order_id == o.id)).scalars().all()
    assert len(assets) == 1


def test_double_light_on_blocked(db):
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=1, unit_price=Decimal("1"))
    svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    with pytest.raises(BusinessError):
        svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
