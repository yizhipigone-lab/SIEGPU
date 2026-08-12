"""EBS 接口 schemas（二期 W1-2）：字段映射 CRUD + 手动触发请求。

同步日志走 service 返回 dict（同 notifications 风格，不用 response_model），故只建映射 schema。
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# 10 类业务域（父计划 §3.1）。Literal 既作文档又给 OpenAPI 下拉。
EntityType = Literal[
    "customer", "supplier", "contract", "invoice", "asset",
    "payment", "prepayment", "lease_disbursement", "repayment", "goods_receipt",
]

TransformRule = Literal["direct", "date_format", "decimal_scale", "constant"]


class FieldMappingCreate(BaseModel):
    entity_type: EntityType
    siegpu_field: str = Field(min_length=1, max_length=100)
    ebs_field: str = Field(min_length=1, max_length=100)
    transform_rule: TransformRule = "direct"
    transform_config: dict | None = None


class FieldMappingUpdate(BaseModel):
    """仅更新传入字段（PATCH 语义）。"""
    ebs_field: str | None = Field(None, min_length=1, max_length=100)
    transform_rule: TransformRule | None = None
    transform_config: dict | None = None


class FieldMappingOut(BaseModel):
    id: UUID
    entity_type: str
    siegpu_field: str
    ebs_field: str
    transform_rule: str
    transform_config: dict | None
    model_config = {"from_attributes": True}


class SyncTriggerRequest(BaseModel):
    """手动触发某实体出站（W1-2 联调/监控页用）。"""
    sync_type: Literal["create", "update", "delete"] = "create"
