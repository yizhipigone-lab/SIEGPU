"""收入确认 + 科目映射（三期 §4.2）。

- revenue_recognitions：权责收入（不含税，面向核算），与开票/收款解耦；billing_id 幂等
  （同一计费单只出一张草稿）；revenue_method 快照合同判定结果（W3-4）。
- gl_account_mappings：业务事件(+核算路径，NULL=通用) → EBS 借贷科目（凭证生成依赖）。
与 alembic 0016 / db/schema.sql 双写一致。
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class RevenueRecognition(UUIDPK, TimestampMixin, Base):
    __tablename__ = "revenue_recognitions"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    billing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("billings.id"), nullable=True)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    recognition_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 不含税
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    booked_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    revenue_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="草稿", nullable=False)  # 草稿/已确认/已同步EBS
    approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("approvals.id"), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voucher_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class GlAccountMapping(UUIDPK, TimestampMixin, Base):
    __tablename__ = "gl_account_mappings"

    business_event: Mapped[str] = mapped_column(String(50), nullable=False)
    revenue_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # NULL=通用
    debit_account: Mapped[str] = mapped_column(String(50), nullable=False)
    credit_account: Mapped[str] = mapped_column(String(50), nullable=False)
    description_template: Mapped[str | None] = mapped_column(String(200), nullable=True)
