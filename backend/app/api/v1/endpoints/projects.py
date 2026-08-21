from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectOut
from app.services import project_service

router = APIRouter()


@router.get("")
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(select(Project)).scalars().all()
    return {"items": [ProjectOut.model_validate(p).model_dump(mode="json") for p in rows], "total": len(rows)}


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = project_service.create_project(db, **{k: v for k, v in payload.model_dump().items() if k != "template_id"})
    # v3.2: 自动创建向导式工作流（支持模板选择）
    from app.services import workflow_service as wf
    wf.create_workflow(db, project_id=p.id, template_id=payload.template_id)
    db.commit()
    return ProjectOut.model_validate(p)

@router.get("/{project_id}/relationships")
def get_project_relationships(project_id: UUID,
                              db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    """项目血缘树：销售合同(→销售订单/被参照采购合同→采购订单→预付款+单台设备) + 金租申请。"""
    tree = project_service.project_relationships(db, project_id)
    if tree is None:
        raise HTTPException(404, "项目不存在")
    return tree
