"""向导式工作台 API。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.models.user import User
from app.schemas.workflow import (
    CompleteStepRequest, MyTaskOut, ProjectWorkflowOut,
    SkipStepRequest, StepConfigUpdate, WorkflowTemplateCreate, WorkflowTemplateOut,
)
from app.services import workflow_service as wf
from app.services import workflow_template_service as tmpl_svc

router = APIRouter(prefix="/api/workflows", tags=["向导式工作台"])


# —— 固定路径端点（必须在 /{project_id} 之前声明，否则被 FastAPI 路径参数遮蔽） ——

@router.get("/my-tasks", response_model=list[MyTaskOut])
def my_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return wf.get_my_tasks(db, user.id)


@router.get("/templates", response_model=list[WorkflowTemplateOut])
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [WorkflowTemplateOut.model_validate(t) for t in tmpl_svc.list_templates(db)]


@router.post("/templates", response_model=WorkflowTemplateOut, status_code=201)
def create_template(payload: WorkflowTemplateCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_role("ADMIN"))):
    tmpl = tmpl_svc.create_template(db, **payload.model_dump())
    db.commit()
    return WorkflowTemplateOut.model_validate(tmpl)


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """项目组合总览：每项目 current_step/状态/角色/停滞天数。"""
    return {"items": wf.portfolio(db)}


# —— 项目流程 ——

@router.get("/{project_id}", response_model=ProjectWorkflowOut)
def get_project_workflow(project_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    pw = wf.get_workflow(db, project_id)
    if not pw:
        from app.core.exceptions import BusinessError
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    return ProjectWorkflowOut.model_validate(pw)


@router.post("/{project_id}/refresh", response_model=ProjectWorkflowOut)
def refresh_workflow(project_id: uuid.UUID, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    pw = wf.refresh_all_steps(db, project_id)
    db.commit()
    return ProjectWorkflowOut.model_validate(pw)


@router.post("/{project_id}/skip/{seq}")
def skip_step(project_id: uuid.UUID, seq: int, payload: SkipStepRequest,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wf.skip_step(db, project_id, seq, payload.reason, user.id)
    db.commit()
    return {"status": "ok"}


@router.post("/{project_id}/steps/{seq}/complete")
def complete_step(project_id: uuid.UUID, seq: int, payload: CompleteStepRequest | None = None,
                  db: Session = Depends(get_db),
                  user: User = Depends(require_role("FINANCE_DIRECTOR", "ADMIN"))):
    wf.mark_step_done(db, project_id, seq, payload.note if payload else None, user.id)
    db.commit()
    return {"status": "ok"}


@router.patch("/{project_id}/steps/{seq}")
def patch_step(project_id: uuid.UUID, seq: int, payload: StepConfigUpdate,
               db: Session = Depends(get_db),
               user: User = Depends(require_role("ADMIN"))):
    wf.update_step_config(db, project_id, seq, **payload.model_dump(exclude_none=True))
    db.commit()
    return {"status": "ok"}
