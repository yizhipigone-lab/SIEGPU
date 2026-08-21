"""对账中心测试（三期 §4.3）：7 维聚合 + 差异标记 golden + 业财一致性 Mock 注入管道。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.device import Device, DeviceStage
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Project
from app.services import approval_service, capital_service
from app.services import contract_service as csvc
from app.services import device_service as dsvc
from app.services import invoice_service as isvc
from app.services import order_service as osvc
from app.services import payment_service
from app.services import reconciliation_service as svc
from app.services import revenue_recognition_service as rsvc
from app.tests.test_prepayment import _bill, _mk


def _project(db, **kw) -> Project:
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}", **kw)
    db.add(p); db.flush(); return p


def _sales(db, p, cust, **kw):
    return csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                                amount=Decimal("1000000"), tax_rate=Decimal("0.13"), **kw)


def _customer(db):
    c = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(c); db.flush(); return c


# ------------------------------ 维度 1：销售全链路 ------------------------------

def test_dim1_flags_golden(db):
    """计费 > 开票 → 已计未开。（四期 W4 期2：收入按开票确认，recognized 与 invoiced 同源——
    未开票时 recognized=0；「已确认未开」在新口径下不可达，不再断言。）"""
    p, c, d = _mk(db, prepayment=None, months=12)  # 销售合同 + 点亮设备
    _bill(db, d, c, 1, date(2026, 1, 31))  # 计费 10000/1.13=8849.57 不含税（不再自动出收入草稿）
    rows = svc.dim1_sales_chain(db)
    mine = next(r for r in rows if r["contract_id"] == str(c.id))
    assert mine["billed"] > 0
    assert mine["invoiced"] == Decimal("0")
    assert mine["recognized"] == Decimal("0")  # 未开票 → 无确认收入
    assert "已计未开" in mine["flags"]
    assert "已开未收" not in mine["flags"]  # 无开票谈不上未收


def test_dim1_paid_no_flags(db):
    """计=开=收=确认 → 无差异标记。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    b = _bill(db, d, c, 1, date(2026, 1, 31))
    inv = isvc.create_invoice(db, contract_id=c.id, amount=b.amount,  # 含税对齐
                              issue_date=date(2026, 2, 1))
    isvc.mark_paid(db, inv.id, date(2026, 2, 5))
    rec = rsvc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    mine = next(r for r in svc.dim1_sales_chain(db) if r["contract_id"] == str(c.id))
    assert mine["flags"] == []
    assert mine["received"] == mine["invoiced"] == mine["billed"]


# ------------------------------ 维度 2/3/4 ------------------------------

def test_dim2_purchase_chain_and_prepayment(db):
    """采购四单：开票 600、核销付款 600 → 已开未付消失；预付款核对列（总额/已结转/余额）。"""
    p = _project(db)
    sup = Supplier(name=f"S-{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add(sup); db.flush()
    parent = _sales(db, p, _customer(db))  # 参照同项目销售合同
    c = csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                             amount=Decimal("900000"), tax_rate=Decimal("0.13"),
                             parent_contract_id=parent.id)
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("600"),
                              issue_date=date(2026, 8, 1))
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                       purchase_value=Decimal("960000"), prepayment_amount=Decimal("12000"))
    rows = svc.dim2_purchase_chain(db)
    mine = next(r for r in rows if r["contract_id"] == str(c.id))
    assert "已开未付" in mine["flags"]
    assert mine["prepayment_total"] == Decimal("12000.00")
    # 付款核销 600 → 无差异
    txn = capital_service.record_transaction(
        db, created_by=None, project_id=p.id, source_type="自有资金", direction="OUT",
        amount=Decimal("600"), transaction_date=date(2026, 8, 10),
        idempotency_key=f"rc-{uuid.uuid4().hex[:8]}")
    payment_service.settle(db, txn_id=txn.id, allocations=[{"invoice_id": inv.id, "amount": "600"}])
    mine = next(r for r in svc.dim2_purchase_chain(db) if r["contract_id"] == str(c.id))
    assert mine["flags"] == [] and mine["paid"] == Decimal("600.00")


def test_dim3_asset_delivery_counts(db):
    """资产交付计数：采购 2 台 → 到货 1（点亮那台也数到货+）→ 转固 1 → 点亮 1；数量不一致标红。"""
    p = _project(db)
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    osvc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=2,
                      unit_price=Decimal("960000"))
    d = dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                           purchase_value=Decimal("960000"), ownership="表内自有")
    d.status = "点亮验收"  # 只 1 台入库且点亮
    db.add(DeviceStage(device_id=d.id, stage="点亮验收", seq=7, status="已完成",
                       actual_date=date(2026, 9, 1)))
    from app.models.asset import Asset
    db.add(Asset(project_id=p.id, equipment_model_id=e.id, device_id=d.id, quantity=1,
                 unit_original_value=Decimal("960000"), total_original_value=Decimal("960000"),
                 operation_status="运营中"))
    db.flush()
    mine = next(r for r in svc.dim3_asset_delivery(db) if r["project_id"] == str(p.id))
    assert (mine["ordered"], mine["devices"], mine["arrived"], mine["capitalized"], mine["lit"]) == (2, 1, 1, 1, 1)
    assert "采购≠入库台数" in mine["flags"]


def test_dim4_supervised_account_retention(db):
    """监管户：回款 10 万 − 还款 3 万 = 留存 7 万 < 最低留存 8 万 → 留存不足标红。"""
    from app.services.contract_amendment_service import set_leasing_rule
    set_leasing_rule(db, rule_key="supervised_min_retention", rule_value="80000")
    p = _project(db)
    cust = _customer(db)
    c = _sales(db, p, cust, collection_account_type="监管户")
    inv = isvc.create_invoice(db, contract_id=c.id, amount=Decimal("100000"),
                              issue_date=date(2026, 8, 1))
    isvc.mark_paid(db, inv.id, date(2026, 8, 5))
    capital_service.record_transaction(
        db, created_by=None, project_id=p.id, source_type="还款", direction="OUT",
        amount=Decimal("30000"), transaction_date=date(2026, 8, 6),
        idempotency_key=f"rc-{uuid.uuid4().hex[:8]}")
    mine = next(r for r in svc.dim4_supervised_accounts(db) if r["contract_id"] == str(c.id))
    assert mine["balance"] == Decimal("70000.00")
    assert "留存不足" in mine["flags"]


# ------------------------------ 维度 5/6/7 ------------------------------

def test_dim5_fx_split_check(db):
    """汇兑核对：有分摊且平 → 无标红；无分摊行 → 未分摊到设备提示。"""
    p = _project(db)
    txn = capital_service.record_transaction(
        db, created_by=None, project_id=p.id, source_type="汇兑损益", direction="IN",
        amount=Decimal("1000"), transaction_date=date(2026, 8, 10), category="汇兑损益",
        idempotency_key=f"fx-{uuid.uuid4().hex[:8]}")
    rows = svc.dim5_fx_check(db)
    mine = next(r for r in rows if r["txn_id"] == str(txn.id))
    assert "未分摊到设备" in mine["flags"]


def test_dim6_inject_demo_pipeline(db):
    """业财一致性 Mock：默认全一致；inject_demo=True → 恰好 3 条业财差异标红（验收管道）。"""
    plain = svc.dim6_ebs_consistency(db, inject_demo=False)
    assert all(it["flags"] == [] for it in plain)
    injected = svc.dim6_ebs_consistency(db, inject_demo=True)
    flagged = [it for it in injected if it["flags"]]
    assert len(flagged) == 3
    assert {it["item"] for it in flagged} == {"应收余额", "资产原值", "资金净头寸"}
    assert all(it["diff"] != 0 for it in flagged)


def test_dim7_only_flagged_and_customer_filter(db):
    """三流差异明细：只列有差异行；按客户筛选。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    _bill(db, d, c, 1, date(2026, 1, 31))  # 已计未开差异
    rows = svc.dim7_flow_diffs(db)
    mine = [r for r in rows if r["contract_no"] == (c.contract_no or "—")]
    assert len(mine) == 1 and "已计未开" in mine[0]["flags"]
    # 客户过滤：换一个客户 → 查不到
    other = _customer(db)
    rows2 = svc.dim7_flow_diffs(db, customer_id=other.id)
    assert all(r["contract_no"] != (c.contract_no or "—") for r in rows2)


# ------------------------------ 维度 8：预付款双轨勾稽（期1 R1 既定后续） ------------------------------

def test_dim8_prepay_parity(db):
    """PREPAY 池余额（资金台账轨）vs Σ设备预付剩余（运营轨）按项目勾稽：
    一致 → 无 flag；双轨有差 → 标「双轨差异」。只列任一轨非零的项目。"""
    p1 = _project(db)
    # 项目1 双轨一致：池挂账 1000 + 设备预付 1000 未结清
    capital_service.record_transaction(db, created_by=None, project_id=p1.id, source_type="预付",
                                       direction="IN", amount=Decimal("1000"),
                                       transaction_date=date(2026, 8, 1), pool="PREPAY",
                                       idempotency_key=f"pp1-{uuid.uuid4().hex[:6]}")
    em = EquipmentModel(name=f"em{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(em); db.flush()
    db.add(Device(sn=f"GPU-{uuid.uuid4().hex[:8]}", project_id=p1.id, equipment_model_id=em.id,
                  prepayment_amount=Decimal("1000")))
    db.flush()

    p2 = _project(db)
    # 项目2 双轨差异：池挂账 500、无设备预付
    capital_service.record_transaction(db, created_by=None, project_id=p2.id, source_type="预付",
                                       direction="IN", amount=Decimal("500"),
                                       transaction_date=date(2026, 8, 1), pool="PREPAY",
                                       idempotency_key=f"pp2-{uuid.uuid4().hex[:6]}")

    rows = svc.dim8_prepay_parity(db)
    by_pid = {r["project_id"]: r for r in rows}
    r1 = by_pid[str(p1.id)]
    assert r1["pool_balance"] == Decimal("1000") and r1["device_remaining"] == Decimal("1000")
    assert r1["diff"] == Decimal("0") and r1["flags"] == []
    r2 = by_pid[str(p2.id)]
    assert r2["diff"] == Decimal("500") and "双轨差异" in r2["flags"]


def test_dim8_settled_device_counts_zero(db):
    """已回核销设备（prepayment_settled=True）剩余按 0 计，不再占运营轨余额。"""
    p = _project(db)
    em = EquipmentModel(name=f"em{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(em); db.flush()
    db.add(Device(sn=f"GPU-{uuid.uuid4().hex[:8]}", project_id=p.id, equipment_model_id=em.id,
                  prepayment_amount=Decimal("800"), prepayment_settled=True,
                  prepayment_settled_amount=Decimal("800")))
    db.flush()
    rows = svc.dim8_prepay_parity(db)
    mine = [r for r in rows if r["project_id"] == str(p.id)]
    # 设备已核销（运营轨 0）且无池流水 → 该项目不出现
    assert mine == []
