"""合同深化 + 单据编号 + 金租规则（二期 W9-10）。

contract_amendments / contract_terminations：合同变更/终止留痕（before/after 快照 + 原因）。
doc_number_rules：单据编号规则表（前缀+日期段+流水）；device_sn 规则回迁一期硬编码
  GPU-{yyyymm}-{seq5}，生成结果必须与一期完全一致（A8）。
leasing_rule_configs：金租规则参数键值表。
与 alembic 0014 / db/schema.sql 双写一致。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class ContractAmendment(UUIDPK, TimestampMixin, Base):
    __tablename__ = "contract_amendments"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    amendment_date: Mapped[date] = mapped_column(Date, nullable=False)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)  # 金额变更/月租变更/期限变更/其他
    before_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ContractTermination(UUIDPK, TimestampMixin, Base):
    __tablename__ = "contract_terminations"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    termination_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    settlement_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class DocNumberRule(UUIDPK, TimestampMixin, Base):
    """单据编号规则：prefix + 日期段(current_period) + seq_digits 位流水。跨日期段流水归零。"""
    __tablename__ = "doc_number_rules"

    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)  # device_sn/contract_no/...
    prefix: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    date_format: Mapped[str | None] = mapped_column(String(20), nullable=True)  # YYYYMM/YYYYMMDD/NULL
    seq_digits: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    current_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LeasingRuleConfig(UUIDPK, TimestampMixin, Base):
    __tablename__ = "leasing_rule_configs"

    rule_key: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_value: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
