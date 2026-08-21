"""W7-8 集成测试：放款条件联动（Phase 4）。

点亮验收完成 → 批次达成率 ≥ orders.disbursement_threshold_pct → 自动建 leasing_process（幂等哨兵）。
含 M4 回归：无金租机构时静默跳过（不抛错、不阻塞点亮完成）。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.delivery import Order
from app.models.leasing import LeasingNode, LeasingProcess
from app.models.master import EquipmentModel, Supplier
from app.models.project import Project
from app.services import device_service as dsvc
from app.utils.disbursement import disbursement_completion_pct


# ---- helpers ----

def _project(db, leasing_mode="直租"):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}", leasing_mode=leasing_mode)
    db.add(p); db.flush(); return p


def _equipment(db):
    e = EquipmentModel(name="H100", category="大卡", gpu_count=8)
    db.add(e); db.flush(); return e


def _funder(db, name="某金租"):
    s = Supplier(name=name, type="资金供应商", is_leasing_org=True)
    db.add(s); db.flush(); return s


def _approve_purchase_acceptance(db, project_id, order_id):
    """四期 W4 期3 硬流转#1：批次设备推进「在途」前，须先有已通过的采购验收。"""
    from app.services import acceptance_service as asvc
    ar = asvc.create_acceptance(db, project_id=project_id, acceptance_type="采购验收", order_id=order_id)
    asvc.approve_acceptance(db, ar, approved_by=None)
    return ar


def _batch_with_devices(db, p, e, n, threshold=Decimal("50"), leasing_mode="直租"):
    batch = Order(project_id=p.id, is_batch=True, batch_name="B",
                  disbursement_threshold_pct=threshold)
    db.add(batch); db.flush()
    devs = []
    for _ in range(n):
        d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                               leasing_mode=leasing_mode, purchase_value=Decimal("960000"))
        d.batch_id = batch.id
        devs.append(d)
    db.flush()
    _approve_purchase_acceptance(db, p.id, batch.id)  # 采购验收前置（期3 硬流转#1）
    return batch, devs


def _advance_to(db, device_id, target_stage, light_on_date=date(2026, 1, 15)):
    for st in dsvc.DEVICE_STAGES[:dsvc.DEVICE_STAGES.index(target_stage) + 1]:
        dsvc.advance_device_stage(db, device_id=device_id, stage=st, status="进行中")
        kw = {"stage": st, "status": "已完成"}
        if st == "点亮验收":
            kw["actual_date"] = light_on_date
        dsvc.advance_device_stage(db, device_id=device_id, **kw)


def _process_count(db):
    return db.execute(select(LeasingProcess).where(LeasingProcess.deleted_at.is_(None))).scalars().all()


def _node_count(db, process_id):
    return db.execute(select(LeasingNode).where(
        LeasingNode.process_id == process_id, LeasingNode.deleted_at.is_(None))).scalars().all()


# ---- 纯函数 ----

def test_disbursement_completion_pct_pure():
    assert disbursement_completion_pct(0, 0) == Decimal("0")       # total=0 防除零
    assert disbursement_completion_pct(0, 2) == Decimal("0")
    assert disbursement_completion_pct(1, 2) == Decimal("50.00")
    assert disbursement_completion_pct(2, 2) == Decimal("100.00")
    assert disbursement_completion_pct(1, 3) == Decimal("33.33")


# ---- hook 集成 ----

def test_threshold_reached_auto_creates_leasing_process(db):
    """2 设备 threshold=50：推 1 台点亮（50%）→ 自动建 leasing_process + 9 节点 + 哨兵写入 + financing_type 派生。"""
    p = _project(db, leasing_mode="直租"); e = _equipment(db); _funder(db)
    batch, devs = _batch_with_devices(db, p, e, 2, threshold=Decimal("50"), leasing_mode="直租")
    _advance_to(db, devs[0].id, "点亮验收")

    db.refresh(batch)
    assert batch.disbursement_todo_process_id is not None
    procs = _process_count(db)
    assert len(procs) == 1
    proc = procs[0]
    assert proc.financing_type == "金租直租"        # 按 proj.leasing_mode 派生
    assert proc.leasing_mode == "直租"
    assert proc.total_amount == Decimal("1920000")  # Σ 批内 2 台 purchase_value
    assert len(_node_count(db, proc.id)) == 9       # 9 标准节点


def test_below_threshold_no_process(db):
    """threshold=80：推 1 台点亮（50%）未达 → 不建 leasing_process，哨兵保持 None。"""
    p = _project(db); e = _equipment(db); _funder(db)
    batch, devs = _batch_with_devices(db, p, e, 2, threshold=Decimal("80"))
    _advance_to(db, devs[0].id, "点亮验收")
    db.refresh(batch)
    assert batch.disbursement_todo_process_id is None
    assert len(_process_count(db)) == 0


def test_idempotent_sentinel_skips_second(db):
    """幂等：哨兵已设 → 推第 2 台点亮不二建（仍只 1 个 process）。"""
    p = _project(db); e = _equipment(db); _funder(db)
    batch, devs = _batch_with_devices(db, p, e, 2, threshold=Decimal("50"))
    _advance_to(db, devs[0].id, "点亮验收")   # 建 1 个
    _advance_to(db, devs[1].id, "点亮验收")   # 哨兵已设 → 跳过
    assert len(_process_count(db)) == 1


def test_rework_lowers_lit_count_and_keeps_sentinel(db):
    """返工后达成率下降（lit 0/2），但哨兵不回退（leasing_process 是已落单业务单据，不对称）。"""
    p = _project(db); e = _equipment(db); _funder(db)
    batch, devs = _batch_with_devices(db, p, e, 2, threshold=Decimal("50"))
    _advance_to(db, devs[0].id, "点亮验收")   # 1/2=50% 达阈值 → 建 process
    db.refresh(batch)
    sentinel = batch.disbursement_todo_process_id
    assert sentinel is not None
    lit, total = dsvc._batch_light_completion(db, batch.id)
    assert (lit, total) == (1, 2)
    # 返工：直租表外设备无资产/计费 → 允许 已完成→不合格
    dsvc.advance_device_stage(db, device_id=devs[0].id, stage="点亮验收", status="不合格")
    lit2, total2 = dsvc._batch_light_completion(db, batch.id)
    assert (lit2, total2) == (0, 2)          # 派生计数下降
    db.refresh(batch)
    assert batch.disbursement_todo_process_id == sentinel  # 哨兵不回退


def test_no_funding_supplier_silent_skip(db):
    """M4 回归：无金租机构 → 静默跳过（不抛错、不阻塞点亮、哨兵 None）。"""
    p = _project(db); e = _equipment(db)
    # 故意不建 资金供应商
    batch, devs = _batch_with_devices(db, p, e, 2, threshold=Decimal("50"))
    _advance_to(db, devs[0].id, "点亮验收")   # 不应抛错
    db.refresh(batch)
    assert batch.disbursement_todo_process_id is None  # 跳过
    assert len(_process_count(db)) == 0
    # 设备点亮本身正常完成
    row = next(s for s in dsvc.list_device_stages(db, devs[0].id) if s.stage == "点亮验收")
    assert row.status == "已完成"
