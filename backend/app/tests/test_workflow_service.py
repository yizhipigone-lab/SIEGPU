"""向导工作流引擎测试：埋点推进、循环连走、Step12/14 区分、completed_by、异常兜底。"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Project
from app.models.step_audit_log import StepAuditLog
from app.services import capital_service as caps
from app.services import contract_service as csvc
from app.services import leasing_service as lsvc
from app.services import order_service as osvc
from app.services import profit_service as psvc
from app.services import sales_order_service as sosvc
from app.services import workflow_service as wfsvc


def _user(db, role="FINANCE_DIRECTOR"):
    from app.models.user import User
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role=role, active=True)
    db.add(u); db.flush(); return u


def _proj(db):
    p = Project(name="P", code=f"c{uuid.uuid4().hex[:6]}"); db.add(p); db.flush(); return p


def _party(db):
    cust = Customer(name=f"cust{uuid.uuid4().hex[:6]}")
    sup = Supplier(name=f"sup{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add_all([cust, sup]); db.flush(); return cust, sup


def _eq(db):
    eq = EquipmentModel(name="H100", category="大卡"); db.add(eq); db.flush(); return eq


def _step(wf, seq):
    return next(s for s in wf.steps if s["seq"] == seq)


# ---------- a) 新埋点触发推进 ----------
def test_sales_order_create_advances_step4(db):
    p = _proj(db); cust, sup = _party(db); eq = _eq(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    assert wf.current_step == 2
    c1 = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                              amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                         amount=Decimal("800000"), tax_rate=Decimal("0.13"))
    assert wf.current_step == 4  # Step2/3 已由合同埋点推进
    sosvc.create_sales_order(db, project_id=p.id, contract_id=c1.id, equipment_model_id=eq.id,
                             quantity=10, monthly_rent_per_unit=Decimal("1000"),
                             total_monthly_rent=Decimal("10000"))
    assert _step(wf, 4)["status"] == "done"
    assert wf.current_step == 5  # Step5 采购订单尚无数据，停下


def test_leasing_create_process_advances_step9(db):
    u = _user(db); p = _proj(db); cust, sup = _party(db); eq = _eq(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    c1 = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                              amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                         amount=Decimal("800000"), tax_rate=Decimal("0.13"))
    sosvc.create_sales_order(db, project_id=p.id, contract_id=c1.id, equipment_model_id=eq.id,
                             quantity=10, monthly_rent_per_unit=Decimal("1000"),
                             total_monthly_rent=Decimal("10000"))
    osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id, quantity=10,
                      unit_price=Decimal("80000"))
    caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                            direction="IN", amount=Decimal("500000"), transaction_date=date(2026, 1, 1))
    caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="自有资金",
                            direction="IN", amount=Decimal("100000"), transaction_date=date(2026, 1, 1))
    caps.record_transaction(db, created_by=u.id, project_id=p.id, source_type="银行流贷",
                            direction="OUT", amount=Decimal("500000"), transaction_date=date(2026, 1, 2))
    assert wf.current_step == 9  # Step2-8 已链式推进
    fin = Supplier(name=f"fin{uuid.uuid4().hex[:6]}", type="资金供应商"); db.add(fin); db.flush()
    lsvc.create_process(db, project_id=p.id, supplier_id=fin.id, total_amount=Decimal("600000"))
    assert _step(wf, 9)["status"] == "done"
    assert wf.current_step == 10  # Step10 需已放款，停下


# ---------- b) 循环推进：一次 after_action 连走多步 ----------
def test_after_action_loops_through_multiple_steps(db):
    p = _proj(db); cust, sup = _party(db); eq = _eq(db)
    # 先造数据（无 workflow，after_action 空转），再建流程从 Step2 一次性连走
    c1 = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                              amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                         amount=Decimal("800000"), tax_rate=Decimal("0.13"))
    sosvc.create_sales_order(db, project_id=p.id, contract_id=c1.id, equipment_model_id=eq.id,
                             quantity=10, monthly_rent_per_unit=Decimal("1000"),
                             total_monthly_rent=Decimal("10000"))
    wf = wfsvc.create_workflow(db, project_id=p.id)
    assert wf.current_step == 2
    wfsvc.after_action(db, p.id)
    assert _step(wf, 2)["status"] == "done"
    assert _step(wf, 3)["status"] == "done"
    assert _step(wf, 4)["status"] == "done"
    assert wf.current_step == 5  # Step5 无采购订单，循环停止
    # 每步 mark_done 都写 audit log
    logs = db.execute(select(StepAuditLog).where(
        StepAuditLog.project_workflow_id == wf.id, StepAuditLog.action == "complete"
    )).scalars().all()
    done_seqs = {l.step_seq for l in logs}
    assert {2, 3, 4} <= done_seqs
    # 自动推进拿不到 operator，completed_by 保持 None
    assert _step(wf, 2)["completed_by"] is None


# ---------- c) Step12（delivery_stages 全 6 阶段）与 Step14（点亮）区分 ----------
def test_step12_delivery_stages_distinct_from_step14(db):
    p = _proj(db); eq = _eq(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=eq.id, quantity=10,
                          unit_price=Decimal("80000"))
    step12 = _step(wf, 12)
    step14 = _step(wf, 14)
    assert step12["completion_check"]["table"] == "delivery_stages"
    assert step14["completion_check"]["table"] == "orders"
    _, stages = osvc.get_order_with_stages(db, o.id)
    assert not wfsvc.check_completion(db, p.id, step12)
    # 完成前 5 阶段 → Step12 仍不通过（需全部 6 阶段）
    for st in stages[:5]:
        osvc.advance_stage(db, stage_id=st.id, status="进行中")
        osvc.advance_stage(db, stage_id=st.id, status="已完成")
    assert not wfsvc.check_completion(db, p.id, step12)
    # 点亮（同事务完成'点亮'阶段 + 订单置已点亮）→ Step12 与 Step14 同时满足
    osvc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    assert wfsvc.check_completion(db, p.id, step12)
    assert wfsvc.check_completion(db, p.id, step14)
    # 端到端：wf 停在 Step12 时，点亮埋点循环推进 12→13（Step13 销售验收无数据停下）
    wf.current_step = 12
    db.flush()
    wfsvc.after_action(db, p.id)
    assert _step(wf, 12)["status"] == "done"
    assert wf.current_step == 13
    assert _step(wf, 14)["status"] == "pending"


# ---------- d) after_action 异常不炸业务（回归） ----------
def test_after_action_exception_does_not_break_business(db, monkeypatch):
    p = _proj(db); cust, sup = _party(db); eq = _eq(db)
    wfsvc.create_workflow(db, project_id=p.id)
    c1 = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                              amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                         amount=Decimal("800000"), tax_rate=Decimal("0.13"))

    def _boom(*a, **kw):
        raise RuntimeError("check exploded")

    monkeypatch.setattr(wfsvc, "check_completion", _boom)
    # check 抛异常被 after_action 吞掉，销售订单正常创建
    so = sosvc.create_sales_order(db, project_id=p.id, contract_id=c1.id, equipment_model_id=eq.id,
                                  quantity=10, monthly_rent_per_unit=Decimal("1000"),
                                  total_monthly_rent=Decimal("10000"))
    assert so.id is not None


# ---------- completed_by 写入 ----------
def test_mark_step_done_and_skip_write_completed_by(db):
    u = _user(db); p = _proj(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    wfsvc.mark_step_done(db, project_id=p.id, seq=2, note="补录", operator_id=u.id)
    assert _step(wf, 2)["completed_by"] == str(u.id)
    wfsvc.skip_step(db, project_id=p.id, seq=3, reason="不需要", operator_id=u.id)
    assert _step(wf, 3)["completed_by"] == str(u.id)


def test_profit_save_scenario_advances_step18(db):
    p = _proj(db)
    wf = wfsvc.create_workflow(db, project_id=p.id)
    # Step18 required=False 不影响主链，直接把 current_step 指到 18 验证埋点
    wf.current_step = 18
    db.flush()
    psvc.save_scenario(db, project_id=p.id, name="实际", params_json={}, result_json={},
                       is_actual=True)
    assert _step(wf, 18)["status"] == "done"


# ---------- 一期 W3-4：设备粒度模板 completion_check ----------

def test_table_classes_includes_device_tables():
    assert "devices" in wfsvc._TABLE_CLASSES and "device_stages" in wfsvc._TABLE_CLASSES
    assert wfsvc._TABLE_CLASSES["devices"].__tablename__ == "devices"
    assert wfsvc._TABLE_CLASSES["device_stages"].__tablename__ == "device_stages"
    # device_stages 经 device_id→Device 间接关联 project_id
    assert wfsvc._FK_TO_PROJECT["device_stages"][1].__tablename__ == "devices"


def _device_flow_step(seq):
    return next(s for s in wfsvc._device_flow_steps() if s["seq"] == seq)


def test_device_flow_step5_devices_completion(db):
    p = _proj(db); eq = _eq(db)
    step5 = _device_flow_step(5)  # 设备导入 → devices
    assert not wfsvc.check_completion(db, p.id, step5)
    from app.services import device_service as dsvc
    dsvc.create_device(db, project_id=p.id, equipment_model_id=eq.id)
    assert wfsvc.check_completion(db, p.id, step5)


def test_device_flow_step6_device_stages_completion_and_cross_project(db):
    from app.models.device import Device, DeviceStage
    p1 = _proj(db); p2 = _proj(db); eq = _eq(db)
    step6 = _device_flow_step(6)  # 设备到货 → device_stages stage=到货 status=已完成 min_count=1
    # p1 一台设备「到货」已完成
    d1 = Device(project_id=p1.id, equipment_model_id=eq.id, sn="GPU-t-1", status="到货")
    db.add(d1); db.flush()
    db.add(DeviceStage(device_id=d1.id, stage="到货", seq=3, status="已完成")); db.flush()
    assert wfsvc.check_completion(db, p1.id, step6)         # p1 满足
    assert not wfsvc.check_completion(db, p2.id, step6)     # p2 无设备 → 不满足（防跨项目误判 D6）
    # p2 加设备但节点非「到货已完成」→ 仍不满足
    d2 = Device(project_id=p2.id, equipment_model_id=eq.id, sn="GPU-t-2", status="订货")
    db.add(d2); db.flush()
    db.add(DeviceStage(device_id=d2.id, stage="订货", seq=1, status="进行中")); db.flush()
    assert not wfsvc.check_completion(db, p2.id, step6)
