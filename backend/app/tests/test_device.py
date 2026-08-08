"""设备实体层测试（一期 W1-2）：SN 生成、设备 CRUD、批次组合/移出守卫、表外备查台账、Excel 导入。"""
import re
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.delivery import Order
from app.models.device import BatchDevice, Device, DeviceStage, OffBalanceRegister
from app.models.master import EquipmentModel
from app.models.project import Project
from app.models.user import User
from app.services import device_service as svc


def _project(db, leasing_mode=None):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}", leasing_mode=leasing_mode)
    db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8); db.add(e); db.flush(); return e


def _device(db, p=None, e=None, **kw):
    p = p or _project(db); e = e or _equipment(db)
    return svc.create_device(db, project_id=p.id, equipment_model_id=e.id, **kw)


def _batch(db, p=None, e=None, name="批次A"):
    p = p or _project(db); e = e or _equipment(db)
    b = Order(project_id=p.id, equipment_model_id=e.id, quantity=1,
              unit_price=Decimal("1"), total_amount=Decimal("1"), batch_name=name)
    db.add(b); db.flush(); return b


def _user(db):
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="DELIVERY", active=True)
    db.add(u); db.flush(); return u


def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    ws.append(["sn", "leasing_mode", "monthly_price", "purchase_value"])
    for r in rows:
        ws.append(r)
    out = BytesIO(); wb.save(out); out.seek(0)
    return out.getvalue()


# ---------- SN 生成 ----------

def test_sn_auto_generation_format(db):
    d = _device(db)
    assert re.fullmatch(r"GPU-\d{6}-\d{5}", d.sn)
    assert d.sn.startswith(f"GPU-{date.today():%Y%m}-")


def test_sn_sequential_and_unique(db):
    p = _project(db); e = _equipment(db)
    d1 = svc.create_device(db, project_id=p.id, equipment_model_id=e.id)
    d2 = svc.create_device(db, project_id=p.id, equipment_model_id=e.id)
    assert d1.sn != d2.sn
    assert int(d2.sn.rsplit("-", 1)[1]) == int(d1.sn.rsplit("-", 1)[1]) + 1


def test_sn_supplied_kept(db):
    d = _device(db, sn="IMPORT-OLD-001")
    assert d.sn == "IMPORT-OLD-001"


# ---------- 设备 CRUD ----------

def test_create_device_defaults(db):
    d = _device(db)
    assert d.status == "订货"
    assert d.prepayment_amount == Decimal("0")
    assert d.ownership is None and d.batch_id is None


def test_create_device_requires_project(db):
    e = _equipment(db)
    with pytest.raises(BusinessError):
        svc.create_device(db, project_id=uuid.uuid4(), equipment_model_id=e.id)


def test_leasing_mode_snapshot_from_project(db):
    p = _project(db, leasing_mode="直租"); e = _equipment(db)
    d = svc.create_device(db, project_id=p.id, equipment_model_id=e.id)
    assert d.leasing_mode == "直租"
    d2 = svc.create_device(db, project_id=p.id, equipment_model_id=e.id, leasing_mode="自有")
    assert d2.leasing_mode == "自有"  # 显式值优先于快照


def test_update_device_and_get(db):
    d = _device(db)
    svc.update_device(db, d.id, monthly_price=Decimal("12345.67"), ownership="表内自有",
                      config={"gpu": "H100", "count": 8})
    got = svc.get_device_or_404(db, d.id)
    assert got.monthly_price == Decimal("12345.67")
    assert got.ownership == "表内自有"
    assert got.config == {"gpu": "H100", "count": 8}


def test_get_device_404(db):
    with pytest.raises(BusinessError):
        svc.get_device_or_404(db, uuid.uuid4())


def test_list_devices_filters(db):
    p = _project(db); e = _equipment(db)
    svc.create_device(db, project_id=p.id, equipment_model_id=e.id)  # 订货
    d2 = svc.create_device(db, project_id=p.id, equipment_model_id=e.id)  # 订货
    # M-2：status 由状态机单点维护，create_device 不再接受 status；推进 d2 到在途
    svc.advance_device_stage(db, device_id=d2.id, stage="订货", status="进行中")
    svc.advance_device_stage(db, device_id=d2.id, stage="订货", status="已完成")
    db.refresh(d2)
    assert d2.status == "在途"
    assert len(svc.list_devices(db, project_id=p.id)) == 2
    assert len(svc.list_devices(db, project_id=p.id, status="在途")) == 1
    assert len(svc.list_devices(db, project_id=p.id, status="订货")) == 1


def test_soft_delete_device(db):
    d = _device(db)
    svc.delete_device(db, d.id)
    with pytest.raises(BusinessError):
        svc.get_device_or_404(db, d.id)
    assert svc.list_devices(db, project_id=d.project_id) == []


# ---------- 批次组合/移出 ----------

def test_add_to_batch_marks_batch_and_flow_type(db):
    d = _device(db); b = _batch(db); u = _user(db)
    bd = svc.add_to_batch(db, device_id=d.id, batch_id=b.id, operator_id=u.id)
    assert bd.action == "加入" and bd.active is True and bd.operated_by == u.id
    db.refresh(b); db.refresh(d)
    assert b.is_batch is True and b.flow_type == "batch"
    assert d.batch_id == b.id


def test_double_assign_rejected(db):
    d = _device(db); b1 = _batch(db, name="A"); b2 = _batch(db, name="B")
    svc.add_to_batch(db, device_id=d.id, batch_id=b1.id)
    with pytest.raises(BusinessError):
        svc.add_to_batch(db, device_id=d.id, batch_id=b2.id)
    with pytest.raises(BusinessError):  # 同批次重复挂载也拒绝
        svc.add_to_batch(db, device_id=d.id, batch_id=b1.id)


def test_remove_from_batch_writes_audit_row(db):
    d = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d.id, batch_id=b.id)
    out = svc.remove_from_batch(db, device_id=d.id)
    assert out.action == "移出" and out.active is False
    db.refresh(d)
    assert d.batch_id is None
    rows = db.execute(select(BatchDevice).where(BatchDevice.device_id == d.id)
                      .execution_options(include_deleted=True)).scalars().all()
    assert {(r.action, r.active) for r in rows} == {("加入", False), ("移出", False)}


def test_rejoin_after_remove_keeps_flow_type(db):
    d = _device(db); b1 = _batch(db, name="A"); b2 = _batch(db, name="B")
    svc.add_to_batch(db, device_id=d.id, batch_id=b1.id)
    svc.remove_from_batch(db, device_id=d.id)
    svc.add_to_batch(db, device_id=d.id, batch_id=b2.id)  # 移出后可挂新批次
    db.refresh(b1)
    assert b1.flow_type == "batch"  # 首次判定固化，不回退


def test_remove_guard_after_shelf(db):
    d = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d.id, batch_id=b.id)
    d.status = "上架"  # 模拟状态机推进（W3-4 起仅状态机可写）
    db.flush()
    with pytest.raises(BusinessError):
        svc.remove_from_batch(db, device_id=d.id)


def test_remove_not_in_batch_404(db):
    d = _device(db)
    with pytest.raises(BusinessError):
        svc.remove_from_batch(db, device_id=d.id)


# ---------- 表外备查台账 ----------

def test_off_balance_register_create_and_list(db):
    d = _device(db)
    r = svc.create_off_balance_register(db, device_id=d.id, register_type="金租直租",
                                        start_date=date(2026, 8, 1), note="直租出表")
    assert r.device_id == d.id and r.register_type == "金租直租"
    rows = svc.list_off_balance_registers(db, device_id=d.id)
    assert len(rows) == 1 and rows[0].note == "直租出表"


def test_off_balance_register_requires_device(db):
    with pytest.raises(BusinessError):
        svc.create_off_balance_register(db, device_id=uuid.uuid4(), register_type="转售")


# ---------- Excel 批量导入 ----------

def test_import_devices_auto_sn(db):
    p = _project(db, leasing_mode="售后回租"); e = _equipment(db)
    data = _xlsx([
        [None, "直租", "12000", "960000"],
        [None, None, "13500.50", "980000"],
    ])
    n = svc.import_devices(db, project_id=p.id, equipment_model_id=e.id, filebytes=data)
    assert n == 2
    rows = svc.list_devices(db, project_id=p.id)
    assert len(rows) == 2
    assert all(re.fullmatch(r"GPU-\d{6}-\d{5}", r.sn) for r in rows)
    by_price = {r.monthly_price: r for r in rows}
    assert by_price[Decimal("12000.00")].leasing_mode == "直租"  # 显式列值优先
    assert by_price[Decimal("13500.50")].leasing_mode == "售后回租"  # 缺省快照自项目
    assert by_price[Decimal("12000.00")].purchase_value == Decimal("960000.00")


def test_import_devices_with_explicit_sn(db):
    p = _project(db); e = _equipment(db)
    n = svc.import_devices(db, project_id=p.id, equipment_model_id=e.id,
                           filebytes=_xlsx([["SUPPLIED-001", None, "9000", "700000"]]))
    assert n == 1
    assert svc.list_devices(db, project_id=p.id)[0].sn == "SUPPLIED-001"


def test_import_devices_requires_project(db):
    e = _equipment(db)
    with pytest.raises(BusinessError):
        svc.import_devices(db, project_id=uuid.uuid4(), equipment_model_id=e.id,
                           filebytes=_xlsx([[None, None, "1", "1"]]))


# ---------- billings.device_id 外键 ----------

def test_billing_device_id_fk(db):
    from app.models.billing import Billing
    from app.models.project import Contract
    p = _project(db); d = _device(db, p=p)
    c = Contract(project_id=p.id, type="SALES", party_type="customer", party_id=uuid.uuid4(),
                 direction="RECEIVABLE", amount=Decimal("1"))
    db.add(c); db.flush()
    b = Billing(project_id=p.id, contract_id=c.id, order_id=None, device_id=d.id,
                period_index=1, period_label="2026-08", billing_date=date(2026, 8, 31),
                days_in_period=31, amount=Decimal("113"), amount_ex_tax=Decimal("100"),
                tax_amount=Decimal("13"))
    db.add(b); db.flush()
    got = db.execute(select(Billing).where(Billing.device_id == d.id)).scalar_one()
    assert got.device_id == d.id


# ============================ 一期 W3-4：设备状态机 ============================

def _st(*pairs):
    """构造内存 DeviceStage 列表（不落库）：(stage, status) 按 seq 升序。"""
    return [DeviceStage(stage=st, seq=i, status=s) for i, (st, s) in enumerate(pairs, 1)]


# ---------- _derive_device_status 纯函数 ----------

def test_derive_empty_stages_returns_first(db):
    assert svc._derive_device_status([]) == "订货"


def test_derive_all_done_returns_lighting(db):
    done = [(st, "已完成") for st in svc.DEVICE_STAGES]
    assert svc._derive_device_status(_st(*done)) == "点亮验收"


def test_derive_first_incomplete_stage_name(db):
    stages = _st(("订货", "已完成"), ("在途", "已完成"), ("到货", "进行中"),
                 ("己方压测", "未开始"), ("上架", "未开始"), ("客户压测", "未开始"), ("点亮验收", "未开始"))
    assert svc._derive_device_status(stages) == "到货"


def test_derive_buhelige_counts_as_incomplete(db):
    # 不合格算未完成：订货/在途已完成，到货不合格 → 瓶颈停在「到货」
    stages = _st(("订货", "已完成"), ("在途", "已完成"), ("到货", "不合格"),
                 ("己方压测", "未开始"), ("上架", "未开始"), ("客户压测", "未开始"), ("点亮验收", "未开始"))
    assert svc._derive_device_status(stages) == "到货"


# ---------- 懒初始化 ----------

def test_ensure_device_stages_creates_7_rows(db):
    d = _device(db)
    rows = svc._ensure_device_stages(db, d.id)
    assert len(rows) == 7
    assert [r.stage for r in rows] == svc.DEVICE_STAGES
    assert [r.seq for r in rows] == list(range(1, 8))
    assert all(r.status == "未开始" for r in rows)


def test_ensure_device_stages_idempotent(db):
    d = _device(db)
    svc._ensure_device_stages(db, d.id)
    svc._ensure_device_stages(db, d.id)
    assert len(svc.list_device_stages(db, d.id)) == 7  # 不重复建


# ---------- advance_device_stage 状态机 ----------

def test_advance_illegal_transition_blocked(db):
    d = _device(db)
    with pytest.raises(BusinessError):  # 未开始 → 已完成 非法
        svc.advance_device_stage(db, device_id=d.id, stage="订货", status="已完成")


def test_advance_unknown_stage_blocked(db):
    d = _device(db)
    with pytest.raises(BusinessError):
        svc.advance_device_stage(db, device_id=d.id, stage="XX", status="进行中")


def test_advance_updates_materialized_status(db):
    d = _device(db)
    svc.advance_device_stage(db, device_id=d.id, stage="订货", status="进行中")
    svc.advance_device_stage(db, device_id=d.id, stage="订货", status="已完成",
                             actual_date=date(2026, 8, 1))
    db.refresh(d)
    assert d.status == "在途"  # 首未完成
    svc.advance_device_stage(db, device_id=d.id, stage="在途", status="进行中")
    svc.advance_device_stage(db, device_id=d.id, stage="在途", status="已完成")
    db.refresh(d)
    assert d.status == "到货"
    row = next(r for r in svc.list_device_stages(db, d.id) if r.stage == "订货")
    assert row.status == "已完成" and row.actual_date == date(2026, 8, 1)


def test_advance_buhelige_rework_path(db):
    d = _device(db)
    for st in ("订货", "在途"):  # 前置节点先完成，否则瓶颈停不到「到货」
        svc.advance_device_stage(db, device_id=d.id, stage=st, status="进行中")
        svc.advance_device_stage(db, device_id=d.id, stage=st, status="已完成")
    # 到货：进行中 → 不合格（返工入口）
    svc.advance_device_stage(db, device_id=d.id, stage="到货", status="进行中")
    svc.advance_device_stage(db, device_id=d.id, stage="到货", status="不合格")
    db.refresh(d)
    assert d.status == "到货"  # 不合格算未完成，瓶颈停此
    # 不合格 → 进行中（返工）允许；再 → 已完成
    svc.advance_device_stage(db, device_id=d.id, stage="到货", status="进行中")
    svc.advance_device_stage(db, device_id=d.id, stage="到货", status="已完成")
    db.refresh(d)
    assert d.status == "己方压测"
    # W5-6 D5：非终态节点 已完成→不合格 现允许（纯质量返工；仅点亮验收有财务守门）
    svc.advance_device_stage(db, device_id=d.id, stage="到货", status="不合格")
    db.refresh(d)
    assert d.status == "到货"  # 不合格算未完成，瓶颈停此


def test_advance_all_stages_to_lighting(db):
    d = _device(db)
    for st in svc.DEVICE_STAGES:
        svc.advance_device_stage(db, device_id=d.id, stage=st, status="进行中")
        svc.advance_device_stage(db, device_id=d.id, stage=st, status="已完成")
    db.refresh(d)
    assert d.status == "点亮验收"


# ---------- 一期 W5-6 Phase D：M-1 翻转 + D5 返工守门 + M-2/M-3 收尾 ----------

def test_resolve_flow_type_device_via_order_id(db):
    """M-1：普通订单经 order_id 直连设备（非批次挂载）→ flow_type='device' → 旧入口被防双计闸拦。"""
    p = _project(db); e = _equipment(db)
    o = Order(project_id=p.id, equipment_model_id=e.id, quantity=1,
              unit_price=Decimal("1"), total_amount=Decimal("1"))
    db.add(o); db.flush()
    assert o.is_batch is False and o.flow_type is None
    svc.create_device(db, project_id=p.id, equipment_model_id=e.id, order_id=o.id)
    db.refresh(o)
    assert svc.resolve_flow_type(db, o) == "device"
    with pytest.raises(BusinessError) as exc:
        svc.assert_legacy_path(db, o)
    assert exc.value.detail["code"] == "FLOW_TYPE_DEVICE"


def test_resolve_flow_type_batch_takes_precedence_over_order_id(db):
    """M-1：批次挂载（batch_id）先命中 batch 分支；order_id 同在也不翻 device。"""
    d = _device(db); b = _batch(db)
    o = Order(project_id=b.project_id, equipment_model_id=b.equipment_model_id, quantity=1,
              unit_price=Decimal("1"), total_amount=Decimal("1"))
    db.add(o); db.flush()
    svc.add_to_batch(db, device_id=d.id, batch_id=b.id)
    db.refresh(b)
    assert svc.resolve_flow_type(db, b) == "batch"  # batch 分支优先


def _advance_to_light(db, d, light_on=date(2026, 9, 15)):
    for st in svc.DEVICE_STAGES:
        svc.advance_device_stage(db, device_id=d.id, stage=st, status="进行中")
        svc.advance_device_stage(db, device_id=d.id, stage=st, status="已完成", actual_date=light_on)


def test_light_rework_blocked_when_on_balance_asset_exists(db):
    """D5：表内自有点亮已激活运营卡 → 点亮验收 已完成→不合格 被 STATE_ERROR 拦（须先红冲/处置）。"""
    p = _project(db); e = _equipment(db)
    d = svc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                          ownership="表内自有", purchase_value=Decimal("960000"))
    _advance_to_light(db, d)
    with pytest.raises(BusinessError) as exc:
        svc.advance_device_stage(db, device_id=d.id, stage="点亮验收", status="不合格")
    assert exc.value.detail["code"] == "STATE_ERROR"


def test_light_rework_allowed_for_off_balance_device(db):
    """D5：表外设备点亮不建资产 → 点亮验收 已完成→不合格 允许（纯质量返工，无财务副作用）。"""
    p = _project(db); e = _equipment(db)
    d = svc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                          ownership="金租表外", leasing_mode="直租", purchase_value=Decimal("960000"))
    _advance_to_light(db, d)
    svc.advance_device_stage(db, device_id=d.id, stage="点亮验收", status="不合格")
    row = next(r for r in svc.list_device_stages(db, d.id) if r.stage == "点亮验收")
    assert row.status == "不合格"


def test_create_device_status_always_dinghuo_schema_dropped(db):
    """M-2：create_device 恒为订货（状态机唯一入口）；DeviceCreate schema 已移除 status 字段。"""
    from app.schemas.device import DeviceCreate
    p = _project(db); e = _equipment(db)
    d = svc.create_device(db, project_id=p.id, equipment_model_id=e.id)
    assert d.status == "订货"
    # schema 不再含 status；Pydantic 默认忽略多余字段，model_validate 不报错也不保留 status
    body = DeviceCreate.model_validate(
        {"project_id": p.id, "equipment_model_id": e.id, "status": "在途"}
    )
    assert not hasattr(body, "status")


# ---------- 批量推进 + 批次聚合 ----------

def test_advance_batch_stages_basic(db):
    d1 = _device(db); d2 = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d1.id, batch_id=b.id)
    svc.add_to_batch(db, device_id=d2.id, batch_id=b.id)
    res = svc.advance_batch_stages(db, batch_id=b.id, stage="订货", status="进行中")
    assert res == {"ok": 2, "fail": 0}
    db.refresh(d1); db.refresh(d2); db.refresh(b)
    assert d1.status == "订货" and d2.status == "订货"
    assert b.batch_status == "订货"  # 聚合瓶颈写入独立字段


def test_advance_batch_stages_fail_path(db):
    """M-3：批内设备该节点已「已完成」→ 批量推进同节点「进行中」被状态机拒 → {ok:0, fail:1}。

    （HTTP /devices/batch-advance 是 4 行透传：调本函数 + commit + return；端到端在 Phase E e2e 覆盖。）
    """
    d1 = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d1.id, batch_id=b.id)
    svc.advance_device_stage(db, device_id=d1.id, stage="订货", status="进行中")
    svc.advance_device_stage(db, device_id=d1.id, stage="订货", status="已完成")
    res = svc.advance_batch_stages(db, batch_id=b.id, stage="订货", status="进行中")
    assert res == {"ok": 0, "fail": 1}  # 已完成→进行中 非法，整批计 fail


def test_advance_batch_isolates_asset_build_failure(db):
    """HIGH 回归（W5-6 审计）：批量推进时某台表内自有设备缺 purchase_value → _sync_device_asset
    在 row.status 已 flush 之后抛 BAD_REQUEST。必须随 SAVEPOINT 回滚该台（不落“已完成”无卡悬挂态），
    批内其余设备正常推进。修复前：失败台节点随端点 commit 落“已完成”却无资产卡，无法重推。"""
    from app.models.asset import Asset
    p = _project(db); e = _equipment(db); b = _batch(db, p=p, e=e)
    d_ok = svc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                             ownership="表内自有", purchase_value=Decimal("960000"))
    d_bad = svc.create_device(db, project_id=p.id, equipment_model_id=e.id, ownership="表内自有")  # 缺 purchase_value
    for d in (d_ok, d_bad):
        svc.add_to_batch(db, device_id=d.id, batch_id=b.id)
        for st in ("订货", "在途", "到货", "己方压测"):
            svc.advance_device_stage(db, device_id=d.id, stage=st, status="进行中")
            svc.advance_device_stage(db, device_id=d.id, stage=st, status="已完成")
        svc.advance_device_stage(db, device_id=d.id, stage="上架", status="进行中")
    res = svc.advance_batch_stages(db, batch_id=b.id, stage="上架", status="已完成")
    assert res == {"ok": 1, "fail": 1}
    bad_row = next(r for r in svc.list_device_stages(db, d_bad.id) if r.stage == "上架")
    assert bad_row.status == "进行中"  # 回滚，非“已完成”——无悬挂
    assert db.execute(select(Asset).where(Asset.device_id == d_bad.id)).scalar_one_or_none() is None  # 未建半卡
    ok_row = next(r for r in svc.list_device_stages(db, d_ok.id) if r.stage == "上架")
    assert ok_row.status == "已完成"  # 成功台不受影响
    assert db.execute(select(Asset).where(Asset.device_id == d_ok.id)).scalar_one() is not None


def test_aggregate_batch_status_all_lit(db):
    d1 = _device(db); d2 = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d1.id, batch_id=b.id)
    svc.add_to_batch(db, device_id=d2.id, batch_id=b.id)
    d1.status = "点亮验收"; d2.status = "点亮验收"; db.flush()
    assert svc._aggregate_batch_status(db, b.id) == "已点亮"
    svc._sync_batch_status(db, b.id)
    db.refresh(b)
    assert b.batch_status == "已点亮"


def test_aggregate_batch_status_bottleneck(db):
    d1 = _device(db); d2 = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d1.id, batch_id=b.id)
    svc.add_to_batch(db, device_id=d2.id, batch_id=b.id)
    d1.status = "到货"; d2.status = "上架"; db.flush()  # 进度不一致
    assert svc._aggregate_batch_status(db, b.id) == "到货"  # 瓶颈=最靠前


# ---------- resolve_flow_type + 防双计闸 ----------

def test_resolve_flow_type_none_when_no_device(db):
    b = _batch(db)  # 普通订单：无设备挂载、flow_type 未固化
    assert svc.resolve_flow_type(db, b) is None


def test_resolve_flow_type_batch_when_device_linked(db):
    d = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d.id, batch_id=b.id)  # 固化 b.flow_type="batch"
    db.refresh(b)
    assert svc.resolve_flow_type(db, b) == "batch"


def test_resolve_flow_type_pinned_returns_pinned(db):
    b = _batch(db)
    b.flow_type = "device"; db.flush()
    assert svc.resolve_flow_type(db, b) == "device"  # 已固化直接返回，不再判定


def test_assert_legacy_path_blocks_batch_order(db):
    b = _batch(db); b.is_batch = True; db.flush()  # is_batch 硬信号
    with pytest.raises(BusinessError):
        svc.assert_legacy_path(db, b)


def test_assert_legacy_path_allows_normal_order(db):
    b = _batch(db)  # is_batch False、无设备、flow_type None
    svc.assert_legacy_path(db, b)  # 不抛


def test_assert_legacy_path_blocks_device_order(db):
    d = _device(db); b = _batch(db)
    svc.add_to_batch(db, device_id=d.id, batch_id=b.id)
    with pytest.raises(BusinessError):
        svc.assert_legacy_path(db, b)
