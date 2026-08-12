"""收入核算路径判定测试（二期 W3-4）：R1/R1b/R2/R3/R4 + 人工覆盖 + EBS 出站。

关键：用真实枚举值造数据（'经营租赁'/'自有'/'直租'/'售后回租'）断言 R1 命中——锁死 D1，
防规则文案与 schema 枚举再次漂移（schema.sql: projects.business_type IN ('经营租赁','转售','自营')）。
db 夹具每用例回滚，互不污染。
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessError
from app.models.ebs import EbsSyncLog
from app.models.master import Customer, Supplier
from app.models.project import Project
from app.models.user import AuditLog, User
from app.services import contract_service as csvc
from app.services import master_service
from app.services import revenue_judge_service as jsvc
from app.utils import revenue_rules as rules


def _project(db, business_type=None, leasing_mode=None) -> Project:
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}",
                business_type=business_type, leasing_mode=leasing_mode)
    db.add(p)
    db.flush()
    return p


def _sales_contract(db, p, **kw):
    cust = master_service.create_entity(db, Customer, {"name": f"判定客户-{uuid.uuid4().hex[:6]}"})
    return csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id,
                                amount=Decimal("100"), tax_rate=Decimal("0.13"), **kw)


def _user(db) -> User:
    u = User(username=f"judge-{uuid.uuid4().hex[:6]}", display_name="财务总监",
             password_hash="x", role="FINANCE_DIRECTOR")
    db.add(u)
    db.flush()
    return u


# ------------------------------ R1 / R1b（真实枚举值，锁 D1） ------------------------------

def test_r1_hits_with_real_enum_values(db):
    """R1：经营租赁 + 自有 + SALES → 经营租赁。用 schema 真实枚举值造数据（锁 D1）。"""
    p = _project(db, business_type="经营租赁", leasing_mode="自有")
    c = _sales_contract(db, p)
    assert c.revenue_method == "经营租赁"
    assert "R1" in c.method_judge_basis


def test_r1b_direct_lease_service_fee(db):
    """R1b：经营租赁 + 直租 → 服务费（按月确认）。"""
    p = _project(db, business_type="经营租赁", leasing_mode="直租")
    c = _sales_contract(db, p)
    assert c.revenue_method == "服务费"
    assert "R1b" in c.method_judge_basis


def test_r1b_leaseback_service_fee(db):
    """R1b：经营租赁 + 售后回租 → 服务费。"""
    p = _project(db, business_type="经营租赁", leasing_mode="售后回租")
    c = _sales_contract(db, p)
    assert c.revenue_method == "服务费"


def test_r1_r1b_mutually_exclusive(db):
    """R1/R1b 互斥：自有→经营租赁（非服务费）；直租→服务费（非经营租赁）。"""
    c_own = _sales_contract(db, _project(db, "经营租赁", "自有"))
    c_lease = _sales_contract(db, _project(db, "经营租赁", "直租"))
    assert c_own.revenue_method == "经营租赁" and c_own.revenue_method != "服务费"
    assert c_lease.revenue_method == "服务费" and c_lease.revenue_method != "经营租赁"


# ------------------------------ R2 / R3 / R4 ------------------------------

def test_r2_net_method(db):
    """R2：上游定价 + 上游担存货风险 + 代理人 → 净额法。"""
    c = _sales_contract(db, _project(db), pricing_authority="上游定价",
                        inventory_risk_bearer="上游", principal_role="代理人")
    assert c.revenue_method == "净额法"
    assert "R2" in c.method_judge_basis


def test_r3_gross_method(db):
    """R3：自主定价 + 我方担存货风险 + 主要责任人（未命中 R1）→ 总额法。"""
    c = _sales_contract(db, _project(db), pricing_authority="自主定价",
                        inventory_risk_bearer="我方", principal_role="主要责任人")
    assert c.revenue_method == "总额法"
    assert "R3" in c.method_judge_basis


def test_r3_not_applied_when_r1_hits(db):
    """R3 条件全部满足但项目命中 R1 → R1 优先（命中即停），不判总额法。"""
    c = _sales_contract(db, _project(db, "经营租赁", "自有"), pricing_authority="自主定价",
                        inventory_risk_bearer="我方", principal_role="主要责任人")
    assert c.revenue_method == "经营租赁"


def test_r4_fallback_pending(db):
    """R4 兜底：转售项目 + 判定输入不匹配 R2/R3 → 待判定。"""
    c = _sales_contract(db, _project(db, "转售", None), pricing_authority="客户定价",
                        inventory_risk_bearer="客户", principal_role="代理人")
    assert c.revenue_method == "待判定"
    assert "R4" in c.method_judge_basis


# ------------------------------ 边界：不判定 / 无上下文 ------------------------------

def test_purchase_contract_not_judged(db):
    """PURCHASE 合同属成本侧，不参与收入判定（即使项目命中 R1 条件）。"""
    p = _project(db, "经营租赁", "自有")
    sup = Supplier(name=f"判定供应商-{uuid.uuid4().hex[:6]}", type="设备供应商")
    db.add(sup)
    db.flush()
    c = csvc.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup.id,
                             amount=Decimal("100"), tax_rate=Decimal("0.13"))
    assert c.revenue_method is None
    r = rules.judge_revenue_method(business_type="经营租赁", leasing_mode="自有", contract_type="PURCHASE")
    assert r.method is None and r.rule == "N/A"


def test_no_judge_context_stays_null(db):
    """无判定上下文（项目无 business_type 且合同无判定输入）→ 保持 NULL，旧流程零变化。"""
    c = _sales_contract(db, _project(db))
    assert c.revenue_method is None
    assert c.method_judge_basis is None


def test_update_contract_triggers_rejudge(db):
    """编辑补录判定输入 → 保存后自动重判（PATCH service 路径）。"""
    c = _sales_contract(db, _project(db))
    assert c.revenue_method is None
    csvc.update_contract(db, c.id, pricing_authority="自主定价",
                         inventory_risk_bearer="我方", principal_role="主要责任人")
    assert c.revenue_method == "总额法"


# ------------------------------ 人工覆盖 ------------------------------

def test_manual_override_records_audit_and_confirmation(db):
    """人工覆盖：写 confirmed_by/at + basis 含原因 + audit REVENUE_OVERRIDE + EBS 出站。"""
    u = _user(db)
    c = _sales_contract(db, _project(db, "转售", None), pricing_authority="客户定价",
                        inventory_risk_bearer="客户", principal_role="代理人")
    assert c.revenue_method == "待判定"
    jsvc.confirm_method(db, c, method="净额法", reason="实质为代销，上游控制定价", actor_id=u.id)
    assert c.revenue_method == "净额法"
    assert "代销" in c.method_judge_basis
    assert c.method_confirmed_by == u.id
    assert c.method_confirmed_at is not None
    log = db.execute(select(AuditLog).where(
        AuditLog.entity_type == "contract", AuditLog.entity_id == c.id,
        AuditLog.action == "REVENUE_OVERRIDE")).scalars().one()
    assert log.before_json["revenue_method"] == "待判定"
    assert log.after_json["revenue_method"] == "净额法"
    # 覆盖结果同步 EBS（method_confirmed=True）
    ebs = db.execute(select(EbsSyncLog).where(
        EbsSyncLog.entity_type == "contract_revenue_method",
        EbsSyncLog.entity_id == str(c.id)).order_by(EbsSyncLog.synced_at.desc())).scalars().first()
    assert ebs.request_payload["revenue_method"] == "净额法"
    assert ebs.request_payload["method_confirmed"] is True


def test_override_requires_reason(db):
    c = _sales_contract(db, _project(db, "转售", None), pricing_authority="客户定价",
                        inventory_risk_bearer="客户", principal_role="代理人")
    with pytest.raises(BusinessError):
        jsvc.confirm_method(db, c, method="净额法", reason="  ")
    with pytest.raises(BusinessError):
        jsvc.confirm_method(db, c, method="不存在的方法", reason="x")


# ------------------------------ EBS 出站 + 幂等 ------------------------------

def test_judge_result_synced_to_ebs_idempotent(db):
    """判定结果快照出站 EBS Mock（entity_type='contract_revenue_method'）；同内容重判幂等跳过。"""
    c = _sales_contract(db, _project(db, "经营租赁", "自有"))
    logs = db.execute(select(EbsSyncLog).where(
        EbsSyncLog.entity_type == "contract_revenue_method",
        EbsSyncLog.entity_id == str(c.id))).scalars().all()
    assert len(logs) == 1
    assert logs[0].status == "MOCK_SUCCESS"
    assert logs[0].request_payload["revenue_method"] == "经营租赁"
    assert logs[0].request_payload["judge_rule"] == "R1"
    # 同内容重判 → entity_version 相同 → 幂等跳过，不新建 log
    jsvc.judge_and_record(db, c)
    n = len(db.execute(select(EbsSyncLog).where(
        EbsSyncLog.entity_type == "contract_revenue_method",
        EbsSyncLog.entity_id == str(c.id))).scalars().all())
    assert n == 1
