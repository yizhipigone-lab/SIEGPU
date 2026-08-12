"""合同变更/终止测试（二期 W9-10）：快照留痕 + 落合同 + 未来期计费联动 + EBS Mock 出站 + 终止。

联动口径：计费按周期现算（无预生成计划行），月租变更落合同 → 下一期计费自动按新值。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.ebs import EbsSyncLog
from app.models.master import Customer, EquipmentModel
from app.models.project import Project
from app.models.user import AuditLog
from app.services import billing_service as bsvc
from app.services import contract_amendment_service as svc
from app.services import contract_service as csvc
from app.services import order_service as osvc


def _contract(db, monthly_rent=Decimal("100000")):
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    return p, csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                                   amount=Decimal("1000000"), tax_rate=Decimal("0.13"),
                                   monthly_rent=monthly_rent)


def test_amend_amount_snapshot_audit_ebs(db):
    """金额变更：before/after 快照 + 落合同 + audit + EBS Mock 出站（sync_type=update）。"""
    p, c = _contract(db)
    row = svc.create_amendment(db, c.id, change_type="金额变更", amendment_date=date(2026, 8, 12),
                               reason="追加 20 台设备", new_amount=Decimal("1200000"))
    assert row.before_json["amount"] == "1000000" and row.after_json["amount"] == "1200000"
    assert csvc.get_contract_or_404(db, c.id).amount == Decimal("1200000")
    log = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "contract", AuditLog.entity_id == c.id,
        AuditLog.action == "UPDATE").order_by(AuditLog.at.desc())).scalars().first()
    assert log.after_json["amount"] == "1200000"
    ebs = db.execute(select(EbsSyncLog).where(
        EbsSyncLog.entity_type == "contract", EbsSyncLog.entity_id == str(c.id),
        EbsSyncLog.sync_type == "update")).scalars().one()
    assert ebs.status == "MOCK_SUCCESS"
    assert ebs.request_payload["amount"] == 1200000.0


def test_amend_requires_reason_and_content(db):
    p, c = _contract(db)
    with pytest.raises(BusinessError):  # 原因必填
        svc.create_amendment(db, c.id, change_type="其他", amendment_date=date(2026, 8, 12),
                             reason=" ", new_amount=Decimal("1"))
    with pytest.raises(BusinessError):  # 变更内容为空
        svc.create_amendment(db, c.id, change_type="其他", amendment_date=date(2026, 8, 12),
                             reason="x")


def test_amend_monthly_rent_links_future_billing(db):
    """月租变更 → 未来期计费自动按新值（计费按周期现算，无预生成计划行）。"""
    p, c = _contract(db, monthly_rent=Decimal("100000"))
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    o = osvc.create_order(db, project_id=p.id, equipment_model_id=e.id, quantity=10,
                          unit_price=Decimal("100000"))
    osvc.light_on(db, order_id=o.id, actual_date=date(2026, 9, 15))
    b1 = bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=1,
                               billing_date=date(2026, 9, 30), created_by=None)
    assert b1.amount == Decimal("53333.33")  # 旧月租 10 万按天折算
    # 变更月租 10万 → 20万
    svc.create_amendment(db, c.id, change_type="月租变更", amendment_date=date(2026, 9, 30),
                         reason="调价", new_monthly_rent=Decimal("200000"))
    b2 = bsvc.generate_billing(db, order_id=o.id, contract_id=c.id, period_index=2,
                               billing_date=date(2026, 10, 31), created_by=None)
    assert b2.amount == Decimal("200000.00")  # 第 2 期按新月租整月


def test_terminate_contract(db):
    p, c = _contract(db)
    row = svc.terminate_contract(db, c.id, termination_date=date(2026, 8, 12),
                                 reason="客户违约", settlement_note="尾款 30 日内结清")
    assert csvc.get_contract_or_404(db, c.id).status == "已终止"
    assert row.reason == "客户违约"
    with pytest.raises(BusinessError):  # 重复终止
        svc.terminate_contract(db, c.id, termination_date=date(2026, 8, 12))
    with pytest.raises(BusinessError):  # 已终止不可变更
        svc.create_amendment(db, c.id, change_type="其他", amendment_date=date(2026, 8, 12),
                             reason="x", new_amount=Decimal("1"))
    # 终止也出站 EBS
    ebs = db.execute(select(EbsSyncLog).where(
        EbsSyncLog.entity_type == "contract", EbsSyncLog.entity_id == str(c.id),
        EbsSyncLog.sync_type == "update")).scalars().all()
    assert len(ebs) >= 1


def test_leasing_rule_upsert(db):
    svc.set_leasing_rule(db, rule_key="disbursement_threshold_default", rule_value="50")
    svc.set_leasing_rule(db, rule_key="disbursement_threshold_default", rule_value="60")
    assert svc.get_leasing_rule(db, "disbursement_threshold_default") == "60"
    assert svc.get_leasing_rule(db, "nonexistent", default="x") == "x"
    assert len(svc.list_leasing_rules(db)) == 1  # upsert 不重复建行
