import uuid
from datetime import datetime

from sqlalchemy import DateTime, event, func
from sqlalchemy.orm import Session, Mapped, mapped_column, with_loader_criteria

from app.core.db import Base


class UUIDPK:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """所有业务表通用：created_at/updated_at（触发器维护）+ deleted_at（软删除）。

    配合下方 do_orm_execute 事件，所有继承本 mixin 的实体 SELECT 默认带
    `deleted_at IS NULL`；需查含已删数据时 `.execution_options(include_deleted=True)`。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Session, "do_orm_execute")
def _soft_delete_default_filter(execute_state):
    """W3：软删除默认过滤——任何 ORM SELECT 自动追加 deleted_at IS NULL。"""
    if execute_state.is_select and not execute_state.execution_options.get("include_deleted"):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TimestampMixin,
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )
