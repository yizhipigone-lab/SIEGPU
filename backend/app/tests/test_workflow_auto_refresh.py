"""#1 架构深化：工作流步骤刷新事件化——service 不再感知工作流。

监听器契约（红→绿）：被追踪实体（_TABLE_CLASSES）flush 落库后，所属项目的
工作流步骤自动推进；service 层不再有手动 after_action 调用（全部由 flush
事件驱动，对外推进语义与手动调用一致：只前进、异常吞掉、audit 留痕）。
"""
import uuid
from decimal import Decimal

from app.models.master import Customer
from app.models.project import Contract, Project
from app.services import workflow_service as wfsvc


def _proj(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def _cust(db):
    c = Customer(name=f"c{uuid.uuid4().hex[:6]}")
    db.add(c); db.flush(); return c


def _step(wf, seq):
    return next(s for s in wf.steps if s["seq"] == seq)


def test_contract_flush_auto_advances_step(db):
    """红：绕过 contract_service 直写 ORM + flush（无人调 after_action）→ 步骤应自动推进。"""
    p = _proj(db)
    cust = _cust(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    assert wf.current_step == 2  # Step1 项目建立已自动完成
    db.add(Contract(project_id=p.id, type="SALES", party_type="customer",
                    party_id=cust.id, direction="RECEIVABLE",
                    amount=Decimal("1000000"), tax_rate=Decimal("0.13")))
    db.flush()
    wf = wfsvc.get_workflow(db, p.id, with_refs=False)
    assert _step(wf, 2)["status"] == "done"
    assert wf.current_step == 3  # Step3 采购合同无数据，停下


def test_auto_advance_loops_multi_step_and_writes_audit(db):
    """一次 flush 满足多步 → 循环连走；每步留 StepAuditLog（与手动 after_action 同语义）。"""
    from sqlalchemy import select

    from app.models.step_audit_log import StepAuditLog

    p = _proj(db)
    cust = _cust(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    # 一次 flush 同时写入 SALES+PURCHASE 两张合同 → Step2/3 连走
    db.add_all([
        Contract(project_id=p.id, type="SALES", party_type="customer",
                 party_id=cust.id, direction="RECEIVABLE",
                 amount=Decimal("1000000"), tax_rate=Decimal("0.13")),
        Contract(project_id=p.id, type="PURCHASE", party_type="supplier",
                 party_id=cust.id, direction="PAYABLE",
                 amount=Decimal("800000"), tax_rate=Decimal("0.13")),
    ])
    db.flush()
    wf = wfsvc.get_workflow(db, p.id, with_refs=False)
    assert _step(wf, 2)["status"] == "done"
    assert _step(wf, 3)["status"] == "done"
    assert wf.current_step == 4  # Step4 销售订单无数据，停下
    logs = db.execute(select(StepAuditLog).where(
        StepAuditLog.project_workflow_id == wf.id,
        StepAuditLog.action == "complete")).scalars().all()
    assert {2, 3} <= {l.step_seq for l in logs}


def test_auto_advance_swallows_check_exception(db):
    """check 抛异常不炸业务（与手动 after_action 的 try/except 同语义）。"""
    p = _proj(db)
    cust = _cust(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)

    orig = wfsvc.check_completion

    def _boom(*a, **kw):
        raise RuntimeError("check exploded")

    wfsvc.check_completion = _boom
    try:
        db.add(Contract(project_id=p.id, type="SALES", party_type="customer",
                        party_id=cust.id, direction="RECEIVABLE",
                        amount=Decimal("1000000"), tax_rate=Decimal("0.13")))
        db.flush()
    finally:
        wfsvc.check_completion = orig
    assert p.id is not None  # flush 不炸
    wf = wfsvc.get_workflow(db, p.id, with_refs=False)
    assert _step(wf, 2)["status"] == "pending"  # 推进失败静默保持


def test_untracked_entity_flush_does_not_touch_workflow(db):
    """未被 _TABLE_CLASSES 追踪的表 flush → 不触发任何推进查询（行为同现状：不推进）。"""
    p = _proj(db)
    cust = _cust(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    from app.models.master import EquipmentModel
    db.add(EquipmentModel(name=f"m{uuid.uuid4().hex[:6]}", category="大卡"))
    db.flush()
    assert wf.current_step == 2
    assert _step(wf, 2)["status"] == "pending"


def test_manual_after_action_still_works(db):
    """after_action 公开 API 保留：手动兜底通道语义不变（终局审计/修数场景用）。"""
    p = _proj(db)
    cust = _cust(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    db.add(Contract(project_id=p.id, type="SALES", party_type="customer",
                    party_id=cust.id, direction="RECEIVABLE",
                    amount=Decimal("1000000"), tax_rate=Decimal("0.13")))
    db.flush()
    wfsvc.after_action(db, p.id)  # 幂等兜底：即使监听器已推进，重复调用无害
    wf = wfsvc.get_workflow(db, p.id, with_refs=False)
    assert _step(wf, 2)["status"] == "done"
    assert wf.current_step == 3
