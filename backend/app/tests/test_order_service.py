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
    # W5-6 回归：legacy 资产仍单张 quantity=N、device_id=None、点亮即运营中
    assert asset.device_id is None
    assert asset.operation_status == "运营中"


def test_double_light_on_blocked(db):
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=1, unit_price=Decimal("1"))
    svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    with pytest.raises(BusinessError):
        svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))


# ---------- 一期 W3-4：is_batch 分支 + 防双计闸 ----------

def test_create_order_is_batch_skips_stages_and_accepts_none(db):
    p = _project(db)
    o = svc.create_order(db, project_id=p.id, is_batch=True, batch_name="批次X")
    assert o.is_batch is True
    assert o.flow_type == "batch"
    assert o.total_amount is None
    assert o.equipment_model_id is None and o.quantity is None and o.unit_price is None
    _, stages = svc.get_order_with_stages(db, o.id)
    assert stages == []  # 不生成 6 条 delivery_stages，节点只走 device_stages


def _order_with_device(db):
    """普通订单挂设备→变 device 路径（真实双计攻击面：残留 6 节点 + 新设备路径）。"""
    from app.services import device_service as dsvc
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id,
                         quantity=2, unit_price=Decimal("1"))
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id)
    dsvc.add_to_batch(db, device_id=d.id, batch_id=o.id)  # 固化 o 为 batch 载体
    return o, d


def test_advance_stage_blocked_for_device_order(db):
    o, _ = _order_with_device(db)
    _, stages = svc.get_order_with_stages(db, o.id)
    with pytest.raises(BusinessError):  # 防双计：旧 6 节点入口被闸
        svc.advance_stage(db, stage_id=stages[0].id, status="进行中")


def test_light_on_blocked_for_device_order(db):
    o, _ = _order_with_device(db)
    with pytest.raises(BusinessError):
        svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))


def test_normal_order_advance_and_light_unaffected(db):
    # 回归：普通订单（无设备挂载）走旧路径不受闸影响
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id,
                         quantity=2, unit_price=Decimal("1"))
    _, stages = svc.get_order_with_stages(db, o.id)
    svc.advance_stage(db, stage_id=stages[0].id, status="进行中")
    svc.advance_stage(db, stage_id=stages[0].id, status="已完成")
    o2, asset = svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    assert o2.status == "已点亮" and asset is not None


def test_order_detail_schema_serializes_batch_nulls():
    """回归：批次订单 4 字段（equipment_model_id/quantity/unit_price/total_amount）可为 None，
    OrderDetail 序列化不得抛 ValidationError→接口 500。
    亲历 bug：A2 放宽 model 列 nullable 但漏改响应 schema，service 测试全绿却 HTTP 500（端到端验证铁律）。
    """
    from app.schemas.order import OrderDetail
    d = OrderDetail(id=uuid.uuid4(), project_id=uuid.uuid4(), equipment_model_id=None,
                    quantity=None, unit_price=None, total_amount=None, status="未点亮",
                    contract_id=None, stages=[])
    assert d.total_amount is None and d.quantity is None
    assert d.equipment_model_id is None and d.unit_price is None


def test_update_order_recomputes_total(db):
    """四期修补：订单可编辑（此前无 PATCH 端点→前端报 405）；改数量/单价自动重算总额。"""
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=500, unit_price=Decimal("4000000"))
    assert o.total_amount == Decimal("2000000000")
    svc.update_order(db, o.id, quantity=600, unit_price=Decimal("3800000"))
    assert o.quantity == 600 and o.unit_price == Decimal("3800000")
    assert o.total_amount == Decimal("2280000000")  # 600 × 3,800,000


def test_update_order_blocked_after_light_on(db):
    """已点亮订单：数量/单价/型号已生成固定资产，禁改（防与资产卡片不一致）。"""
    p = _project(db); e = _equipment(db)
    o = svc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=10, unit_price=Decimal("100000"))
    svc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    with pytest.raises(BusinessError):
        svc.update_order(db, o.id, quantity=20)
