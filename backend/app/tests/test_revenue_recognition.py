"""收入确认测试（四期 W4 期2 改版）：**开票**驱动收入（不再按计费）。

口径：对账单确认 → 开票 → 开票即出收入确认草稿（不含税=发票不含税）→ 审批 → Mock 凭证 → EBS 出站。
golden：凭证借贷科目按 gl_account_mappings（方法精确匹配优先，通用兜底）；EBS 载荷含凭证。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.ebs import EbsSyncLog
from app.models.master import Customer
from app.models.project import Project
from app.models.revenue import RevenueRecognition
from app.services import approval_service
from app.services import contract_service as csvc
from app.services import invoice_service as isvc
from app.services import revenue_recognition_service as svc


def _mk_contract(db, *, revenue_method=None):
    """项目 + 客户 + 销售合同（可带核算路径）。"""
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    cust = Customer(name=f"C-{uuid.uuid4().hex[:6]}")
    db.add(cust); db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                             amount=Decimal("1000000"), tax_rate=Decimal("0.13"))
    if revenue_method:
        c.revenue_method = revenue_method
        db.flush()
    return p, c


def _invoice(db, c, amount=Decimal("113000"), issue_date=date(2026, 1, 31)):
    """开一张销售方向发票（含税 113000 → 不含税 100000），自动出收入草稿。"""
    return isvc.create_invoice(db, contract_id=c.id, amount=amount,
                               invoice_no=f"INV-{uuid.uuid4().hex[:6]}", issue_date=issue_date)


def test_draft_auto_generated_on_invoice(db):
    """开票 → 自动出草稿：amount=发票不含税、invoice_id 关联、状态草稿、挂审批单。"""
    p, c = _mk_contract(db)
    inv = _invoice(db, c)
    recs = svc.list_recognitions(db, project_id=p.id)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.status == "草稿"
    assert rec.amount == inv.amount_ex_tax  # 权责口径=发票不含税
    assert rec.invoice_id == inv.id
    assert rec.approval_id is not None  # 自动挂审批
    # 幂等：同发票再触发不重复
    svc.generate_draft_for_invoice(db, inv)
    assert len(svc.list_recognitions(db, project_id=p.id)) == 1


def test_purchase_invoice_no_revenue(db):
    """采购方向发票不确认收入（仅销售发票）。"""
    from app.models.master import Supplier
    p, c = _mk_contract(db)
    sup = Supplier(name=f"S-{uuid.uuid4().hex[:6]}", type="设备供应商"); db.add(sup); db.flush()
    pc = csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                              amount=Decimal("1000000"), tax_rate=Decimal("0.13"),
                              parent_contract_id=c.id)
    isvc.create_invoice(db, contract_id=pc.id, amount=Decimal("113000"), issue_date=date(2026, 1, 31))
    assert svc.list_recognitions(db, project_id=p.id) == []


def test_draft_snapshots_contract_revenue_method(db):
    """revenue_method 快照自合同判定结果（W3-4 联动）。"""
    p, c = _mk_contract(db, revenue_method="经营租赁")
    _invoice(db, c)
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    assert rec.revenue_method == "经营租赁"


def test_approve_confirm_voucher_ebs_golden(db):
    """审批通过 → 已确认+凭证（经营租赁精确映射借 1122.01/贷 6001.01）→ EBS 出站 → 已同步EBS。"""
    svc.create_mapping(db, business_event="收入确认", revenue_method="经营租赁",
                       debit_account="1122.01", credit_account="6001.01",
                       description_template="确认{period}经营租赁收入")
    svc.create_mapping(db, business_event="收入确认", revenue_method=None,
                       debit_account="1122.99", credit_account="6001.99")  # 通用兜底（不应命中）
    p, c = _mk_contract(db, revenue_method="经营租赁")
    inv = _invoice(db, c)
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    rec = db.get(RevenueRecognition, rec.id)
    assert rec.status == "已同步EBS"
    assert rec.confirmed_at is not None
    v = rec.voucher_json
    assert v["debit_account"] == "1122.01" and v["credit_account"] == "6001.01"
    assert v["description"] == f"确认{rec.period_label}经营租赁收入"
    assert v["amount"] == float(inv.amount_ex_tax)
    # EBS 出站载荷含凭证
    log = db.execute(select(EbsSyncLog).where(
        EbsSyncLog.entity_type == "revenue_recognition",
        EbsSyncLog.entity_id == str(rec.id))).scalars().one()
    assert log.status == "MOCK_SUCCESS"
    assert log.request_payload["voucher"]["debit_account"] == "1122.01"


def test_generic_mapping_fallback(db):
    """无方法精确映射 → 通用（NULL）兜底。"""
    svc.create_mapping(db, business_event="收入确认", revenue_method=None,
                       debit_account="1122.99", credit_account="6001.99")
    p, c = _mk_contract(db, revenue_method="总额法")
    _invoice(db, c)
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    rec = db.get(RevenueRecognition, rec.id)
    assert rec.voucher_json["debit_account"] == "1122.99"
    assert rec.voucher_json["mapping_missing"] is False


def test_missing_mapping_marks_flag(db):
    """无映射：凭证仍出但 mapping_missing=True（不静默错账，提示补映射）。"""
    p, c = _mk_contract(db)
    _invoice(db, c)
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    rec = db.get(RevenueRecognition, rec.id)
    assert rec.voucher_json["mapping_missing"] is True
    assert rec.status == "已同步EBS"  # Mock 出站不受缺映射影响


def test_reject_keeps_draft(db):
    p, c = _mk_contract(db)
    _invoice(db, c)
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.reject(db, rec.approval_id, reason="金额待复核")
    assert db.get(RevenueRecognition, rec.id).status == "草稿"


def test_mapping_duplicate_blocked(db):
    svc.create_mapping(db, business_event="收入确认", revenue_method=None,
                       debit_account="a", credit_account="b")
    with pytest.raises(BusinessError):
        svc.create_mapping(db, business_event="收入确认", revenue_method=None,
                           debit_account="x", credit_account="y")
