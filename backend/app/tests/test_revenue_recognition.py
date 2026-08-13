"""收入确认测试（三期 §4.2）：计费自动出草稿（不含税+方法快照）→ 审批通过 → Mock 凭证 → EBS 出站。

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
from app.models.revenue import RevenueRecognition
from app.services import approval_service
from app.services import revenue_recognition_service as svc
from app.tests.test_prepayment import _mk, _bill  # 复用：项目+合同+点亮设备+按台计费


def test_draft_auto_generated_on_billing(db):
    """计费生成 → 自动出草稿：amount=不含税、revenue_method 快照、状态草稿、挂审批单。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    b = _bill(db, d, c, 1, date(2026, 1, 31))
    recs = svc.list_recognitions(db, project_id=p.id)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.status == "草稿"
    assert rec.amount == b.amount_ex_tax  # 权责口径=不含税
    assert rec.billing_id == b.id and rec.device_id == d.id
    assert rec.approval_id is not None  # 自动挂审批
    # 幂等：同 billing 再触发不重复
    svc.generate_draft_for_billing(db, b)
    assert len(svc.list_recognitions(db, project_id=p.id)) == 1


def test_draft_snapshots_contract_revenue_method(db):
    """revenue_method 快照自合同判定结果（W3-4 联动）。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    c.revenue_method = "经营租赁"  # 模拟 W3-4 判定结果
    db.flush()
    _bill(db, d, c, 1, date(2026, 1, 31))
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    assert rec.revenue_method == "经营租赁"


def test_approve_confirm_voucher_ebs_golden(db):
    """审批通过 → 已确认+凭证（经营租赁精确映射借 1122.01/贷 6001.01）→ EBS 出站 → 已同步EBS。"""
    svc.create_mapping(db, business_event="收入确认", revenue_method="经营租赁",
                       debit_account="1122.01", credit_account="6001.01",
                       description_template="确认{period}经营租赁收入")
    svc.create_mapping(db, business_event="收入确认", revenue_method=None,
                       debit_account="1122.99", credit_account="6001.99")  # 通用兜底（不应命中）
    p, c, d = _mk(db, prepayment=None, months=12)
    c.revenue_method = "经营租赁"
    db.flush()
    b = _bill(db, d, c, 1, date(2026, 1, 31))
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    rec = db.get(RevenueRecognition, rec.id)
    assert rec.status == "已同步EBS"
    assert rec.confirmed_at is not None
    v = rec.voucher_json
    assert v["debit_account"] == "1122.01" and v["credit_account"] == "6001.01"
    assert v["description"] == f"确认{rec.period_label}经营租赁收入"
    assert v["amount"] == float(b.amount_ex_tax)
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
    p, c, d = _mk(db, prepayment=None, months=12)
    c.revenue_method = "总额法"
    db.flush()
    _bill(db, d, c, 1, date(2026, 1, 31))
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    rec = db.get(RevenueRecognition, rec.id)
    assert rec.voucher_json["debit_account"] == "1122.99"
    assert rec.voucher_json["mapping_missing"] is False


def test_missing_mapping_marks_flag(db):
    """无映射：凭证仍出但 mapping_missing=True（不静默错账，提示补映射）。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    _bill(db, d, c, 1, date(2026, 1, 31))
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.approve(db, rec.approval_id)
    rec = db.get(RevenueRecognition, rec.id)
    assert rec.voucher_json["mapping_missing"] is True
    assert rec.status == "已同步EBS"  # Mock 出站不受缺映射影响


def test_reject_keeps_draft(db):
    p, c, d = _mk(db, prepayment=None, months=12)
    _bill(db, d, c, 1, date(2026, 1, 31))
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    approval_service.reject(db, rec.approval_id, reason="金额待复核")
    assert db.get(RevenueRecognition, rec.id).status == "草稿"


def test_backfill_existing_billings(db):
    """存量计费补草稿（幂等）：先删钩子产物模拟存量，再 backfill。"""
    p, c, d = _mk(db, prepayment=None, months=12)
    b = _bill(db, d, c, 1, date(2026, 1, 31))
    # 模拟存量：删掉自动草稿后 backfill
    rec = svc.list_recognitions(db, project_id=p.id)[0]
    rec.deleted_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    db.flush()
    n = svc.backfill_drafts(db, project_id=p.id)
    # 软删的草稿不算存在（查询自带 deleted 过滤）→ 补建 1 张；uq 索引只看活跃行不冲突
    assert n == 1
    assert svc.backfill_drafts(db, project_id=p.id) == 0  # 二次幂等


def test_mapping_duplicate_blocked(db):
    svc.create_mapping(db, business_event="收入确认", revenue_method=None,
                       debit_account="a", credit_account="b")
    with pytest.raises(BusinessError):
        svc.create_mapping(db, business_event="收入确认", revenue_method=None,
                           debit_account="x", credit_account="y")
