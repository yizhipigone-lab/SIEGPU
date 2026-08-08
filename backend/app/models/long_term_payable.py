import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class LongTermPayable(UUIDPK, TimestampMixin, Base):
    """长期应付款（一期 W7-8 售后回租）：per-device 粒度。

    回租出售时确认（leaseback_sale_service）：principal_amount = 出售价（用于偿付金租机构）。
    carrying_amount / sale_gain_loss / original_end_date / paid_amount 为**钩子位**——
    本期只存值供报表/审计追溯，**不做会计分录**（二期业财一体化 EBS）。

    uq_ltp_device（部分唯一）保证一台售后回租设备全局仅一条 active 应付 → 干净幂等键 +
    per-device 损益可追溯。聚合到 leasing_process 级用 SUM 查询。
    """

    __tablename__ = "long_term_payables"
    __table_args__ = (
        # 一设备一应付（三方声明纪律，镜像 assets.uq_assets_device / billings.uq_billing_period）。
        Index("uq_ltp_device", "device_id", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    leasing_process_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leasing_processes.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)  # 金租机构
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 出售价（偿付本金）
    carrying_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 钩子位：出售日账面价值
    sale_gain_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 钩子位：出售损益（可负=损失）
    original_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 钩子位：原折旧到期日（二期 reverse 用）
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)  # 钩子位
    status: Mapped[str] = mapped_column(String(20), default="已确认", nullable=False)  # 已确认/部分偿还/已结清/已撤销
    confirm_date: Mapped[date | None] = mapped_column(Date, nullable=True)
