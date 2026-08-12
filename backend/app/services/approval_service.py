"""通用审批服务（二期 W11-12）：单级落地，level/max_level 留多级扩展。

biz_type 覆盖：项目立项 / 付款申请 / 预付款 / 预算调整 / 监管划转 / 合同变更 / 收入确认。
立项双轨（D4）：审批为可选——项目创建主流程不变（直接建），只有显式 submit 的项目才走审批；
无审批记录的项目/单据走原直接路径（wizard-workspace 等存量流程零回归）。
service 不 commit 铁律：只 flush。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.payment import Approval


def submit(db: Session, *, biz_type: str, biz_id=None, title: str,
           submitted_by: uuid.UUID | None = None) -> Approval:
    """提交审批（一单同时只允一条待审批）。返回审批行。"""
    if biz_id is not None:
        pending = db.execute(select(Approval).where(
            Approval.biz_type == biz_type, Approval.biz_id == biz_id,
            Approval.status == "待审批")).scalars().first()
        if pending is not None:
            raise BusinessError("DUPLICATE", "该单据已有待审批记录", 409)
    a = Approval(biz_type=biz_type, biz_id=biz_id, title=title, submitted_by=submitted_by)
    db.add(a)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=submitted_by, action="CREATE", target_type="approval",
               target_id=a.id, after_json={"biz_type": biz_type, "title": title})
    return a


def approve(db: Session, approval_id, *, approved_by=None) -> Approval:
    a = _get_or_404(db, approval_id)
    if a.status != "待审批":
        raise BusinessError("ILLEGAL_TRANSITION", f"审批状态 {a.status} 不可通过", 409)
    a.status = "已通过"
    a.approved_by = approved_by
    a.approved_at = datetime.now(timezone.utc)
    db.flush()
    _cascade(db, a, approved=True, actor_id=approved_by)
    from app.services import audit_service as _audit
    _audit.log(db, user_id=approved_by, action="UPDATE",
               target_type="approval", target_id=a.id, after_json={"status": "已通过"})
    return a


def reject(db: Session, approval_id, *, reason: str, approved_by=None) -> Approval:
    """驳回必须填原因。"""
    if not reason or not reason.strip():
        raise BusinessError("BAD_REQUEST", "驳回必须填写原因", 400)
    a = _get_or_404(db, approval_id)
    if a.status != "待审批":
        raise BusinessError("ILLEGAL_TRANSITION", f"审批状态 {a.status} 不可驳回", 409)
    a.status = "已驳回"
    a.reject_reason = reason.strip()
    a.approved_by = approved_by
    a.approved_at = datetime.now(timezone.utc)
    db.flush()
    _cascade(db, a, approved=False, actor_id=approved_by)
    from app.services import audit_service as _audit
    _audit.log(db, user_id=approved_by, action="UPDATE", target_type="approval",
               target_id=a.id, after_json={"status": "已驳回", "reason": reason.strip()})
    return a


def _get_or_404(db: Session, approval_id) -> Approval:
    a = db.get(Approval, approval_id)
    if not a or a.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "审批单不存在", 404)
    return a


def _cascade(db: Session, a: Approval, *, approved: bool, actor_id=None) -> None:
    """审批结果联动业务单据状态（付款申请：已通过→已批准 / 已驳回→已驳回）。
    项目立项双轨（D4）：审批只改项目审批留痕，不动项目主流程。"""
    if a.biz_type == "付款申请" and a.biz_id:
        from app.models.payment import PaymentRequest
        pr = db.get(PaymentRequest, a.biz_id)
        if pr is not None:
            pr.status = "已批准" if approved else "已驳回"
            db.flush()


def list_approvals(db: Session, *, biz_type=None, status=None) -> list[Approval]:
    stmt = select(Approval).order_by(Approval.created_at.desc())
    if biz_type:
        stmt = stmt.where(Approval.biz_type == biz_type)
    if status:
        stmt = stmt.where(Approval.status == status)
    return list(db.execute(stmt).scalars().all())
