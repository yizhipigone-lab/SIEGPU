"""通用审批测试（二期 W11-12）：提交/通过/驳回 + 驳回原因必填 + 重复待审批拦截 + 立项双轨（D4）。
db 夹具每用例回滚，互不污染。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.master import Customer
from app.models.project import Project
from app.services import approval_service as svc
from app.services import payment_service


def _project(db) -> Project:
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush(); return p


def test_submit_approve_cascades_payment_request(db):
    """审批通过 → 付款申请状态级联「已批准」。"""
    p = _project(db)
    pr = payment_service.create_request(db, project_id=p.id, amount=Decimal("1000"))
    assert pr.status == "待审批" and pr.approval_id is not None
    svc.approve(db, pr.approval_id)
    assert db.get(type(pr), pr.id).status == "已批准"
    a = db.get(svc.Approval, pr.approval_id) if hasattr(svc, "Approval") else None
    appr = svc.list_approvals(db, biz_type="付款申请")[0]
    assert appr.status == "已通过" and appr.approved_at is not None


def test_reject_requires_reason(db):
    p = _project(db)
    pr = payment_service.create_request(db, project_id=p.id, amount=Decimal("1000"))
    with pytest.raises(BusinessError):
        svc.reject(db, pr.approval_id, reason="  ")
    svc.reject(db, pr.approval_id, reason="预算不足")
    appr = svc.list_approvals(db, biz_type="付款申请")[0]
    assert appr.status == "已驳回" and appr.reject_reason == "预算不足"
    assert db.get(type(pr), pr.id).status == "已驳回"  # 级联


def test_duplicate_pending_blocked(db):
    p = _project(db)
    svc.submit(db, biz_type="项目立项", biz_id=p.id, title="立项审批")
    with pytest.raises(BusinessError):
        svc.submit(db, biz_type="项目立项", biz_id=p.id, title="重复提交")


def test_settled_approval_immutable(db):
    p = _project(db)
    a = svc.submit(db, biz_type="项目立项", biz_id=p.id, title="x")
    svc.approve(db, a.id)
    with pytest.raises(BusinessError):
        svc.approve(db, a.id)
    with pytest.raises(BusinessError):
        svc.reject(db, a.id, reason="r")


def test_project_initiation_dual_track(db):
    """D4 双轨：项目直接创建主流程不变；审批为可选附加（通过/驳回都不动项目主状态）。"""
    p = _project(db)  # 直接建项目（原路径，无审批）
    assert p.status == "进行中"
    a = svc.submit(db, biz_type="项目立项", biz_id=p.id, title=f"立项审批 {p.name}")
    svc.approve(db, a.id)
    assert db.get(Project, p.id).status == "进行中"  # 审批不改项目主流程状态
