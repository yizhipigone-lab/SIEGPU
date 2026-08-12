"""EBS 接口管理端点（二期 W1-2）：字段映射 CRUD + 同步日志查询 + 手动触发/重试。

出站仅 SIEGPU→EBS（Mock）；映射配置编辑、日志查询、失败重试供 EbsMonitor.vue 使用。
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.ebs import (
    FieldMappingCreate,
    FieldMappingOut,
    FieldMappingUpdate,
    SyncTriggerRequest,
)
from app.services import ebs_sync_service as svc

router = APIRouter()


# ------------------------------ 字段映射 CRUD ------------------------------

@router.get("/mappings")
def list_mappings(entity_type: str | None = None,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_mappings(db, entity_type)
    return {"items": [FieldMappingOut.model_validate(r).model_dump(mode="json") for r in rows], "total": len(rows)}


@router.post("/mappings", response_model=FieldMappingOut, status_code=201)
def create_mapping(payload: FieldMappingCreate,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        m = svc.create_mapping(db, payload.model_dump())
    except ValueError as e:  # 同 entity_type+siegpu_field 已存在 → 409
        raise HTTPException(status_code=409, detail=str(e))
    db.commit()
    return FieldMappingOut.model_validate(m)


@router.patch("/mappings/{mid}", response_model=FieldMappingOut)
def update_mapping(mid: UUID, payload: FieldMappingUpdate,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = svc.update_mapping(db, mid, payload.model_dump(exclude_unset=True))
    if m is None:
        raise HTTPException(status_code=404, detail="映射不存在")
    db.commit()
    return FieldMappingOut.model_validate(m)


@router.delete("/mappings/{mid}", status_code=204)
def delete_mapping(mid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not svc.soft_delete_mapping(db, mid):
        raise HTTPException(status_code=404, detail="映射不存在")
    db.commit()


# ------------------------------ 同步日志 ------------------------------

@router.get("/logs")
def list_logs(entity_type: str | None = None, status: str | None = None,
              limit: int = Query(100, ge=1, le=500),
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_logs(db, entity_type, status, limit)
    return {"items": [svc.log_to_dict(r) for r in rows], "total": len(rows)}


# ------------------------------ 手动触发 / 重试 ------------------------------

@router.post("/sync/{entity_type}/{entity_id}")
def trigger_sync(entity_type: str, entity_id: str, payload: SyncTriggerRequest,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """手动触发某实体出站。实体不存在 → 404；未知 entity_type → 400。"""
    try:
        result = svc.sync_by_type(db, entity_type, entity_id, sync_type=payload.sync_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail=f"实体不存在：{entity_type}/{entity_id}")
    db.commit()
    return result


@router.post("/logs/{log_id}/retry")
def retry_sync(log_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """重试一条同步（按原实体重新出站）。原 FAILED log 留审计，返回新 log。日志不存在 → 404。"""
    result = svc.retry_log(db, log_id)
    if result is None:
        raise HTTPException(status_code=404, detail="日志不存在")
    db.commit()
    return result
