import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Asset(UUIDPK, TimestampMixin, Base):
    """资产卡。一期 W5-6 起一机一卡（device_id 部分唯一）+ 转固/运营分离。

    两段式生命周期：上架建卡时 operation_status='已转固未运营'、折旧字段全 None、
    start_date/end_date=None；点亮验收激活后填齐折旧字段并置 operation_status='运营中'。
    """

    __tablename__ = "assets"
    __table_args__ = (
        # W5-6：一机一卡部分唯一索引（schema.sql:573 / alembic 0007:41-44 一致）。
        # device_id IS NULL 的 legacy 批量卡不受约束；与 billings 的 uq_billing_period 同纪律三方声明。
        Index("uq_assets_device", "device_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND device_id IS NOT NULL")),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    equipment_model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipment_models.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_original_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_original_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    residual_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.10"), nullable=False)
    residual_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    depreciable_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    annual_depreciation: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    monthly_depreciation: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="折旧中", nullable=False)
    operation_status: Mapped[str] = mapped_column(String(20), default="已转固未运营", nullable=False)
