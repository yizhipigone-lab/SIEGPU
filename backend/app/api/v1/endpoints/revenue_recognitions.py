"""收入确认 + 科目映射端点（三期 §4.2）。main.py 挂 prefix=/api。
确认动作走审批中心（approvals biz_type='收入确认' 通过/驳回自动级联），本模块无独立 confirm 端点。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.revenue import MappingIn, MappingOut, RecognitionOut
from app.services import revenue_recognition_service as svc

router = APIRouter()


@router.get("/revenue-recognitions")
def list_recognitions(project_id: UUID | None = None, status: str | None = None,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_recognitions(db, project_id=project_id, status=status)
    return {"items": [RecognitionOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}


@router.post("/revenue-recognitions/generate")
def backfill(project_id: UUID | None = None,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """存量计费补确认草稿（幂等）。返回补建条数。"""
    n = svc.backfill_drafts(db, project_id=project_id)
    db.commit()
    return {"created": n}


@router.get("/gl-account-mappings")
def list_mappings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_mappings(db)
    return {"items": [MappingOut.model_validate(m).model_dump(mode="json") for m in rows],
            "total": len(rows)}


@router.post("/gl-account-mappings", response_model=MappingOut, status_code=201)
def create_mapping(payload: MappingIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = svc.create_mapping(db, **payload.model_dump())
    db.commit()
    return MappingOut.model_validate(m)
