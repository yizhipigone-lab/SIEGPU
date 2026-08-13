"""收入确认服务（三期 §4.2）。

链路：计费生成 → 自动出确认**草稿**（不含税，单台粒度，billing_id 幂等）→ 审批（approvals
biz_type='收入确认'，复用审批中心）→ 通过 → 已确认 + 按 gl_account_mappings 生成 Mock 凭证
→ EBS 出站 → 已同步EBS。驳回 → 保持草稿。
口径（父计划 §4.2）：billings=应收计费（含税，对客户）；revenue_recognitions=权责收入（不含税，
对核算）；与开票/收款解耦；billing_id 关联不强制一一对应。
service 不 commit 铁律：只 flush。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.billing import Billing
from app.models.project import Contract, Project
from app.models.revenue import GlAccountMapping, RevenueRecognition
from app.services import approval_service


# ------------------------------ 草稿生成（计费钩子） ------------------------------

def generate_draft_for_billing(db: Session, billing: Billing,
                               actor_id: uuid.UUID | None = None) -> RevenueRecognition | None:
    """按台/按单计费生成后自动出确认草稿。幂等：同一 billing 只出一张（DB 部分唯一索引兜底）。"""
    existing = db.execute(select(RevenueRecognition).where(
        RevenueRecognition.billing_id == billing.id)).scalar_one_or_none()
    if existing is not None:
        return existing
    c = db.get(Contract, billing.contract_id)
    batch_id = None
    if billing.device_id:
        from app.models.device import Device
        d = db.get(Device, billing.device_id)
        batch_id = d.batch_id if d else None
    rec = RevenueRecognition(
        project_id=billing.project_id, contract_id=billing.contract_id,
        batch_id=batch_id, device_id=billing.device_id, billing_id=billing.id,
        period_label=billing.period_label, recognition_date=billing.billing_date,
        amount=billing.amount_ex_tax,  # 不含税（权责口径）
        currency_code=billing.currency_code, booked_rate=billing.booked_rate,
        revenue_method=c.revenue_method if c else None,  # 快照合同判定结果（W3-4）
        status="草稿",
    )
    db.add(rec)
    db.flush()
    proj = db.get(Project, billing.project_id)
    a = approval_service.submit(
        db, biz_type="收入确认", biz_id=rec.id,
        title=f"收入确认 {rec.period_label} 不含税 {rec.amount}（项目 {proj.name if proj else billing.project_id}）",
        submitted_by=actor_id)
    rec.approval_id = a.id
    db.flush()
    return rec


def backfill_drafts(db: Session, project_id=None) -> int:
    """存量计费补草稿（未出草稿的 billings 逐张补）。返回补建条数。"""
    stmt = select(Billing).where(Billing.status != "已红冲")
    if project_id:
        stmt = stmt.where(Billing.project_id == project_id)
    n = 0
    for b in db.execute(stmt).scalars().all():
        exists = db.execute(select(RevenueRecognition.id).where(
            RevenueRecognition.billing_id == b.id)).first()
        if exists is not None:
            continue
        generate_draft_for_billing(db, b)
        n += 1
    return n


# ------------------------------ 审批结果级联 ------------------------------

def on_approval_result(db: Session, recognition_id, *, approved: bool,
                       actor_id: uuid.UUID | None = None) -> None:
    """approval_service._cascade 调用。通过 → 已确认 + Mock 凭证 + EBS 出站 → 已同步EBS；驳回 → 保持草稿。"""
    rec = db.get(RevenueRecognition, recognition_id)
    if rec is None or rec.deleted_at is not None:
        return
    if not approved:
        return  # 驳回：保持草稿，可修改后重新提交（本期不自动重提）
    if rec.status != "草稿":
        return
    rec.status = "已确认"
    rec.confirmed_by = actor_id
    rec.confirmed_at = datetime.now(timezone.utc)
    rec.voucher_json = _build_voucher(db, rec)
    db.flush()
    # Mock 凭证出站 EBS（应收/总账），成功即 已同步EBS
    from app.services import ebs_sync_service as _ebs
    try:
        payload = {"recognition_id": str(rec.id), "period_label": rec.period_label,
                   "amount": float(rec.amount), "revenue_method": rec.revenue_method,
                   "voucher": rec.voucher_json}
        res = _ebs.sync_entity(db, "revenue_recognition", rec.id, payload)
        if res.get("status") in ("MOCK_SUCCESS", "SUCCESS"):
            rec.status = "已同步EBS"
            db.flush()
    except Exception:  # noqa: BLE001 —— EBS 旁路不阻断确认（留 已确认，可在 EBS 页重试）
        import logging
        logging.getLogger(__name__).warning("revenue_recognition: EBS sync failed for %s", rec.id)


def _build_voucher(db: Session, rec: RevenueRecognition) -> dict:
    """按 gl_account_mappings 生成 Mock 凭证：business_event='收入确认' + revenue_method 精确匹配，
    无则回退通用（revenue_method IS NULL）。无映射 → accounts=None（凭证仍出，标注缺映射）。"""
    m = db.execute(select(GlAccountMapping).where(
        GlAccountMapping.business_event == "收入确认",
        GlAccountMapping.revenue_method == rec.revenue_method)).scalars().first()
    if m is None:
        m = db.execute(select(GlAccountMapping).where(
            GlAccountMapping.business_event == "收入确认",
            GlAccountMapping.revenue_method.is_(None))).scalars().first()
    desc = None
    if m and m.description_template:
        desc = m.description_template.replace("{period}", rec.period_label)
    return {
        "business_event": "收入确认",
        "debit_account": m.debit_account if m else None,
        "credit_account": m.credit_account if m else None,
        "amount": float(rec.amount),
        "currency_code": rec.currency_code,
        "booked_rate": float(rec.booked_rate) if rec.booked_rate is not None else None,
        "description": desc or f"收入确认 {rec.period_label}",
        "mapping_missing": m is None,
    }


# ------------------------------ 科目映射 CRUD ------------------------------

def list_mappings(db: Session) -> list[GlAccountMapping]:
    return list(db.execute(select(GlAccountMapping).order_by(
        GlAccountMapping.business_event, GlAccountMapping.revenue_method)).scalars().all())


def create_mapping(db: Session, *, business_event: str, revenue_method=None,
                   debit_account: str, credit_account: str, description_template=None) -> GlAccountMapping:
    exists = db.execute(select(GlAccountMapping.id).where(
        GlAccountMapping.business_event == business_event,
        GlAccountMapping.revenue_method.is_(None) if revenue_method is None
        else GlAccountMapping.revenue_method == revenue_method)).first()
    if exists is not None:
        raise BusinessError("DUPLICATE", f"映射已存在：{business_event}/{revenue_method or '通用'}", 409)
    m = GlAccountMapping(business_event=business_event, revenue_method=revenue_method,
                         debit_account=debit_account, credit_account=credit_account,
                         description_template=description_template)
    db.add(m)
    db.flush()
    return m


# ------------------------------ 查询 ------------------------------

def list_recognitions(db: Session, project_id=None, status=None) -> list[RevenueRecognition]:
    stmt = select(RevenueRecognition).order_by(RevenueRecognition.created_at.desc())
    if project_id:
        stmt = stmt.where(RevenueRecognition.project_id == project_id)
    if status:
        stmt = stmt.where(RevenueRecognition.status == status)
    return list(db.execute(stmt).scalars().all())
