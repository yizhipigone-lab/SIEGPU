"""一期 W5-6 历史迁移纯函数测试（D6）：批量卡拆分 + Σ 不变量 + 尾差吸收 + 空库 no-op。

split_bulk_assets_to_per_device 在 alembic 0007 内以 op.get_bind() 传入原始连接调用；
此处直接传 conftest 的 db Session（Session.execute(text(...)) 与 Connection 同构），同事务回滚。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.models.asset import Asset
from app.models.master import EquipmentModel
from app.models.project import Project
from app.utils.data_migration import split_bulk_assets_to_per_device


def _project(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8); db.add(e); db.flush(); return e


def test_split_bulk_card_per_device_with_sigma_and_tail(db):
    """quantity=3、total=1,000,000（不可整除）→ 3 devices + 3 单台卡；末期吸收 0.01 尾差；Σ 精确；原卡软删。"""
    p = _project(db); e = _equipment(db)
    bulk = Asset(
        project_id=p.id, equipment_model_id=e.id, quantity=3,
        unit_original_value=Decimal("333333.33"), total_original_value=Decimal("1000000.00"),
        residual_rate=Decimal("0.10"),
        residual_value=Decimal("100000.00"), depreciable_value=Decimal("900000.00"),
        annual_depreciation=Decimal("180000.00"), monthly_depreciation=Decimal("15000.00"),
        start_date=date(2026, 7, 1), end_date=date(2031, 7, 1),
        status="折旧中", operation_status="运营中",
    )
    db.add(bulk); db.flush()  # 显式 flush：raw SELECT 才看得到（autoflush 只对 ORM 查询触发）

    result = split_bulk_assets_to_per_device(db)

    assert result == {"split_cards": 3, "created_devices": 3}

    # 原批量卡软删
    soft = db.execute(text("SELECT deleted_at FROM assets WHERE id=:i"),
                      {"i": bulk.id}).scalar_one()
    assert soft is not None

    # 3 张单台卡（运营中、device_id 关联、quantity=1、末期吸收尾差）
    cards = db.execute(text(
        "SELECT unit_original_value, monthly_depreciation, device_id, operation_status, quantity "
        "FROM assets WHERE deleted_at IS NULL ORDER BY unit_original_value, monthly_depreciation"
    )).all()
    assert len(cards) == 3
    assert [c[0] for c in cards] == [Decimal("333333.33"), Decimal("333333.33"), Decimal("333333.34")]
    assert all(c[2] is not None and c[3] == "运营中" and c[4] == 1 for c in cards)

    # Σ unit 精确 == 原总原值
    sum_unit = db.execute(text(
        "SELECT SUM(unit_original_value) FROM assets WHERE deleted_at IS NULL")).scalar_one()
    assert sum_unit == Decimal("1000000.00")
    # Σ monthly 容差内
    sum_monthly = db.execute(text(
        "SELECT SUM(monthly_depreciation) FROM assets WHERE deleted_at IS NULL")).scalar_one()
    assert abs(sum_monthly - Decimal("15000.00")) <= Decimal("0.01") * 3

    # 3 台 device（status=点亮验收、ownership=表内自有）
    devs = db.execute(text(
        "SELECT status, ownership FROM devices WHERE project_id=:p"), {"p": p.id}).all()
    assert len(devs) == 3
    assert all(d[0] == "点亮验收" and d[1] == "表内自有" for d in devs)


def test_empty_db_is_noop(db):
    """无批量卡 → no-op，返回 0（不抛、不写）。"""
    result = split_bulk_assets_to_per_device(db)
    assert result == {"split_cards": 0, "created_devices": 0}


def test_never_operating_bulk_card_splits_to_unoperating_cards(db):
    """start_date/monthly 均空的批量卡（数据异常但 backfill 已置运营中）→ 拆为已转固未运营卡、device 停上架。"""
    p = _project(db); e = _equipment(db)
    bulk = Asset(
        project_id=p.id, equipment_model_id=e.id, quantity=2,
        unit_original_value=Decimal("500000.00"), total_original_value=Decimal("1000000.00"),
        residual_rate=Decimal("0.10"),
        residual_value=None, depreciable_value=None,
        annual_depreciation=None, monthly_depreciation=None,
        start_date=None, end_date=None,
        status="折旧中", operation_status="运营中",  # backfill 置运营中，但折旧字段空
    )
    db.add(bulk); db.flush()

    result = split_bulk_assets_to_per_device(db)

    assert result["split_cards"] == 2
    cards = db.execute(text(
        "SELECT operation_status, monthly_depreciation, start_date, device_id "
        "FROM assets WHERE deleted_at IS NULL")).all()
    assert len(cards) == 2
    assert all(c[0] == "已转固未运营" and c[1] is None and c[2] is None and c[3] is not None for c in cards)
    devs = db.execute(text(
        "SELECT status FROM devices WHERE project_id=:p"), {"p": p.id}).all()
    assert all(d[0] == "上架" for d in devs)  # 未点亮 → device 停在上架
