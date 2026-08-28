from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.exceptions import BusinessError
from app.models.project import Project
from app.models.user import User
from app.schemas.contract import (AmendmentIn, AmendmentOut, ContractCreate, ContractOut,
                                  ContractUpdate, JudgePreviewOut, MethodConfirmIn,
                                  TerminationIn, TerminationOut)
from app.services import contract_amendment_service as amend_svc
from app.services import contract_service as svc
from app.services import pdf_service
from app.services import revenue_judge_service as judge_svc
from app.utils import revenue_rules

router = APIRouter()


@router.get("")
def list_contracts(project_id: UUID | None = None, type: str | None = None,
                   parent_contract_id: UUID | None = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_contracts(db, project_id=project_id, type=type, parent_contract_id=parent_contract_id)
    # 缺陷#8：批量附加明细行（避免 N+1）
    from app.services.contract_line_service import load_line_items
    from app.schemas.contract import ContractLineItemOut
    lines = load_line_items(db, [r.id for r in rows])
    out = []
    for c in rows:
        d = ContractOut.model_validate(c).model_dump(mode="json")
        d["line_items"] = [ContractLineItemOut.model_validate(li).model_dump(mode="json")
                           for li in lines.get(c.id, [])]
        out.append(d)
    return {"items": out, "total": len(out)}


@router.post("", response_model=ContractOut, status_code=201)
def create_contract(payload: ContractCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.create_contract(db, actor_id=user.id, **payload.model_dump())
    db.commit()
    db.refresh(c)
    # 缺陷#8：创建响应带明细行
    from app.services.contract_line_service import load_line_items
    from app.schemas.contract import ContractLineItemOut
    d = ContractOut.model_validate(c).model_dump(mode="json")
    d["line_items"] = [ContractLineItemOut.model_validate(li).model_dump(mode="json")
                       for li in load_line_items(db, [c.id]).get(c.id, [])]
    return d


# 二期 W3-4：判定预览（纯函数不落库，前端表单实时预览）—— 须在 /{cid} 之前声明，防被 cid 捕获
@router.get("/judge-preview", response_model=JudgePreviewOut)
def judge_preview(project_id: UUID, type: str,
                  pricing_authority: str | None = None, inventory_risk_bearer: str | None = None,
                  principal_role: str | None = None,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    proj = db.get(Project, project_id)
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    r = revenue_rules.judge_revenue_method(
        business_type=proj.business_type, leasing_mode=proj.leasing_mode, contract_type=type,
        pricing_authority=pricing_authority, inventory_risk_bearer=inventory_risk_bearer,
        principal_role=principal_role)
    return JudgePreviewOut(method=r.method, rule=r.rule, basis=r.basis)


# 二期 W9-10：变更/终止列表（query 参数版，供合同详情聚合 tab；须在 /{cid} 之前声明）
@router.get("/amendments")
def list_amendments(contract_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = amend_svc.list_amendments(db, contract_id)
    return {"items": [AmendmentOut.model_validate(r).model_dump(mode="json") for r in rows], "total": len(rows)}


@router.get("/terminations")
def list_terminations(contract_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = amend_svc.list_terminations(db, contract_id)
    return {"items": [TerminationOut.model_validate(r).model_dump(mode="json") for r in rows], "total": len(rows)}


@router.get("/{cid}", response_model=ContractOut)
def get_contract(cid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.get_contract_or_404(db, cid)
    from app.services.contract_line_service import load_line_items
    from app.schemas.contract import ContractLineItemOut
    lines = load_line_items(db, [c.id]).get(c.id, [])
    d = ContractOut.model_validate(c).model_dump(mode="json")
    d["line_items"] = [ContractLineItemOut.model_validate(li).model_dump(mode="json") for li in lines]
    return d


@router.patch("/{cid}", response_model=ContractOut)
def update_contract(cid: UUID, payload: ContractUpdate,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """二期 W3-4：合同编辑（白名单字段）+ 保存后自动重判。"""
    c = svc.update_contract(db, cid, actor_id=user.id, **payload.model_dump(exclude_unset=True))
    db.commit()
    return ContractOut.model_validate(c)


@router.post("/{cid}/judge", response_model=ContractOut)
def rejudge_contract(cid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """二期 W3-4：手动重判（无条件重跑规则，覆盖系统判定快照；不动人工 confirmed 留痕）。"""
    c = svc.get_contract_or_404(db, cid)
    judge_svc.judge_and_record(db, c, actor_id=user.id)
    db.commit()
    return ContractOut.model_validate(c)


@router.post("/{cid}/confirm-method", response_model=ContractOut)
def confirm_method(cid: UUID, payload: MethodConfirmIn,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """二期 W3-4：人工覆盖/确认核算路径（原因必填，记 audit + confirmed 留痕 + EBS 出站）。"""
    c = svc.get_contract_or_404(db, cid)
    judge_svc.confirm_method(db, c, method=payload.method, reason=payload.reason, actor_id=user.id)
    db.commit()
    return ContractOut.model_validate(c)


# ------------------------------ 二期 W9-10：变更/终止 ------------------------------

@router.post("/{cid}/amendments", response_model=AmendmentOut, status_code=201)
def create_amendment(cid: UUID, payload: AmendmentIn,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """合同变更（金额/月租/止日）：快照留痕 + 落合同（未来期计费自动按新值）+ EBS 出站。"""
    from datetime import date as _date
    row = amend_svc.create_amendment(
        db, cid, change_type=payload.change_type,
        amendment_date=payload.amendment_date or _date.today(),
        reason=payload.reason, new_amount=payload.new_amount,
        new_monthly_rent=payload.new_monthly_rent, new_end_date=payload.new_end_date,
        actor_id=user.id)
    db.commit()
    return AmendmentOut.model_validate(row)


@router.post("/{cid}/terminate", response_model=TerminationOut, status_code=201)
def terminate_contract(cid: UUID, payload: TerminationIn,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from datetime import date as _date
    row = amend_svc.terminate_contract(
        db, cid, termination_date=payload.termination_date or _date.today(),
        reason=payload.reason, settlement_note=payload.settlement_note, actor_id=user.id)
    db.commit()
    return TerminationOut.model_validate(row)


@router.delete("/{cid}", status_code=204)
def delete_contract(cid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.get_contract_or_404(db, cid)
    from datetime import datetime, timezone
    c.deleted_at = datetime.now(timezone.utc)
    # #4 审计补漏：走查发现端点级软删除原先不留审计（架构评审 2026-08-27 §3.1）
    from app.services import audit_service as _audit
    _audit.log(db, user_id=user.id, action="DELETE", target_type="contract",
               target_id=c.id, after_json={"contract_no": c.contract_no or "",
                                           "status": c.status, "soft_deleted": True})
    db.commit()


@router.get("/{cid}/pdf")
def contract_pdf(cid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """F4：合同 PDF 实时生成（不落库，浏览器直接下载）。"""
    buf = pdf_service.render_contract_pdf(db, cid)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="contract-{cid}.pdf"'},
    )
