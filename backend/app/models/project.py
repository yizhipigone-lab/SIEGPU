import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Project(UUIDPK, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="进行中", nullable=False)
    total_investment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 一期 W1-2：设备层扩展
    business_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 经营租赁/转售/自营
    leasing_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 自有/直租/售后回租
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    financing_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 融资方案摘要


class Contract(UUIDPK, TimestampMixin, Base):
    __tablename__ = "contracts"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # SALES/PURCHASE
    party_type: Mapped[str] = mapped_column(String(20), nullable=False)  # supplier/customer
    party_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(12), nullable=False)  # RECEIVABLE/PAYABLE
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.13"), nullable=False)
    monthly_rent: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    parent_contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="草稿", nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    leasing_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 一期 W1-2：合同模式快照（自有/直租/售后回租）
