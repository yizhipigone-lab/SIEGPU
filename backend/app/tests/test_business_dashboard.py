"""经营看板测试（三期 §4.5）：核心指标 golden + 待办中心计数 + 资金预测 + EBS 状态。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.leasing import LeasingProcess
from app.services import approval_service, business_board_service as svc
from app.services import invoice_service as isvc
from app.tests.test_prepayment import _bill, _mk


def test_metrics_golden(db):
    """核心指标：本月新签合同 100 万 / 回款 / 开票 / 确认收入（审批通过）/ 设备点亮进度。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    b = _bill(db, d, c, 1, date(2026, 1, 31))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=b.amount, issue_date=date(2026, 2, 1))
    isvc.mark_paid(db, inv.id, date(2026, 2, 5))
    from app.services import revenue_recognition_service as rsvc
    rec = rsvc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    m = svc.business_board(db)["metrics"]
    assert m["contract_amount_current"] == Decimal("1000000.00")  # 本月新签（测试库当天建）
    assert m["total_received"] == m["invoiced_total"] == b.amount_ex_tax
    assert m["recognized_total"] == b.amount_ex_tax
    assert m["device_lit"] == 1 and m["device_total"] == 1


def test_metrics_leasing_balance(db):
    """融资余额 = 已放款 − 已还本金。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    from app.models.master import Supplier
    sup = Supplier(name=f"S-{uuid.uuid4().hex[:6]}", type="资金供应商")
    db.add(sup); db.flush()
    db.add(LeasingProcess(project_id=p.id, supplier_id=sup.id,
                          total_amount=Decimal("500000"), status="已放款"))
    db.flush()
    m = svc.business_board(db)["metrics"]
    assert m["leasing_balance"] == Decimal("500000.00")


def test_todo_center_counts(db):
    """待办中心：审批待办（开票驱动的收入确认审批）+ 预付款未结清设备计数。"""
    p, c, d = _mk(db, prepayment=Decimal("12000"), months=12)
    _bill(db, d, c, 1, date(2026, 1, 31))
    # 四期 W4 期2：收入按开票确认——开票即出收入草稿并挂审批
    isvc.create_invoice(db, contract_id=c.id, amount=Decimal("113000"), issue_date=date(2026, 2, 1))
    todos = svc.business_board(db)["todo_center"]
    by_kind = {t["kind"]: t for t in todos}
    assert by_kind["付款/收入审批"]["count"] >= 1  # 收入确认草稿自动挂审批
    assert by_kind["预付款未结清设备"]["count"] == 1
    assert by_kind["资金缺口预警"]["count"] == 0  # 无流水无应付 → 无缺口


def test_forecast_three_months(db):
    """预测概览：恰好未来 3 个月、期初=上期末滚动；流出=当月到期还款+未付采购票。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    # 采购发票下月到期未付 1130
    from app.models.master import Supplier
    from app.services import contract_service as csvc
    sup = Supplier(name=f"S-{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add(sup); db.flush()
    pc = csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                              amount=Decimal("900000"), tax_rate=Decimal("0.13"),
                              parent_contract_id=c.id)  # 参照同项目销售合同（≤销售额度 100 万）
    today = date.today()
    ny, nm = (today.year, today.month + 1) if today.month < 12 else (today.year + 1, 1)
    isvc.create_invoice(db, contract_id=pc.id, amount=Decimal("1130"),
                        issue_date=today, due_date=date(ny, nm, 15))
    fc = svc.business_board(db)["forecast"]
    assert len(fc) == 3
    assert fc[0]["month"] == f"{ny}-{nm:02d}"
    assert fc[0]["outflow"] == Decimal("1130.00")
    assert fc[1]["opening"] == fc[0]["closing"]  # 滚动


def test_ebs_stats(db):
    """EBS 状态卡：同步一条后 success ≥1。"""
    from app.models.master import Customer
    from app.services import ebs_sync_service, master_service
    c = master_service.create_entity(db, Customer, {"name": f"C-{uuid.uuid4().hex[:6]}"})
    ebs_sync_service.sync_customer(db, c.id)
    ebs = svc.business_board(db)["ebs"]
    assert ebs["success"] >= 1 and ebs["last_synced_at"] is not None
