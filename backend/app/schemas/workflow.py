"""向导式工作台 — Pydantic schemas。"""
import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class WorkflowTemplateCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = None
    steps: list[dict]
    is_active: bool = True


class WorkflowTemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    steps: list[dict]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectWorkflowOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    template_id: uuid.UUID | None = None
    steps: list[dict]
    current_step: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MyTaskOut(BaseModel):
    project_id: uuid.UUID
    project_name: str
    step_seq: int
    step_name: str
    doer_role: str
    drawer: bool
    drawer_schema: str | None = None
    module: str


class SkipStepRequest(BaseModel):
    reason: str = Field(min_length=1)


class CompleteStepRequest(BaseModel):
    note: str | None = None


class StepConfigUpdate(BaseModel):
    required: bool | None = None
    drawer: bool | None = None
    doer_role: str | None = None
    approver_role: str | None = None
