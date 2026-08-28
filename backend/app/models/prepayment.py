"""预付款台账（S3 收敛：D2 裁定翻盘——台账表为单一真源，devices 字段降级为分摊展示）。

缺陷#5/#6 修复：台账行含 登记时间(payment_date)/供应商(supplier_id)/采购合同(contract_id)，
与资金流水共享 idempotency_key（/capital/prepayment 同事务落账），设备登记预付款自动落账。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Prepayment(UUIDPK, TimestampMixin, Base):
    """预付款台账行。

    - 手工池预付（/capital/prepayment）：一行，device_id 空，幂等键与双流水共享
    - 设备登记预付（devices.prepayment_amount>0）：自动落一行，device_id 非空，
      payment_date 取 devices.prepayment_date（可空=待补），supplier_id 取设备供应商（可空，K2）
    - 结转（settle_for_billing）扣 settled_amount；settled_amount >= amount → 已结清（派生）
    """

    __tablename__ = "prepayments"
    __table_args__ = (
        Index("uq_prepay_idem", "idempotency_key", unique=True,
              postgresql_where=text("idempotency_key IS NOT NULL")),
        Index("idx_prepay_project", "project_id",
              postgresql_where=text("deleted_at IS NULL")),
        Index("idx_prepay_device", "device_id",
              postgresql_where=text("deleted_at IS NULL AND device_id IS NOT NULL")),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 登记时间（设备来源待补可空）
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
