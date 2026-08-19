import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
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
    # 二期 W3-4：收入核算路径判定（输入 3 字段 + 判定结果快照 + 确认留痕）
    pricing_authority: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 定价权：自主定价/客户定价/上游定价
    inventory_risk_bearer: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 存货风险承担：我方/客户/上游
    principal_role: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 主要责任人/代理人
    revenue_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 核算路径：总额法/净额法/经营租赁/服务费/待判定
    method_judge_basis: Mapped[str | None] = mapped_column(Text, nullable=True)  # 判定依据（自动生成）
    method_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    method_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 二期 W5-6：币种与记账汇率（nullable；NULL=人民币，存量语义不变）
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    booked_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    # 二期 W9-10：合同深化（全 nullable）
    purchase_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    warranty_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    penalty_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prepayment_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    collection_account_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 四期 W4：合同类型 + 含税总额 + 算力租赁租期（全 nullable，纯加法；amount 仍为不含税口径，下游核算不变）
    biz_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 合同类型：算力租赁/转售/服务
    amount_incl_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 合同金额（含税）
    lease_months: Mapped[int | None] = mapped_column(nullable=True)  # 租期(月)，仅算力租赁填写
