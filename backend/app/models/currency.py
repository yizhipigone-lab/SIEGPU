"""币种与汇率（二期 W5-6）：币种主数据 + 汇率表 + 汇兑损益科目规则。

量纲铁律（docs/superpowers/specs/2026-08-12-w5-6-unit-dimension-table.md）：
rate 存 DECIMAL(18,8) 全精度（直接标价法：1 外币 = N 元人民币），永不 round；
金额两位小数，「外币 × rate → 人民币」唯一乘除跳才 q2。
与 alembic 0012 / db/schema.sql 双写一致。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Currency(UUIDPK, TimestampMixin, Base):
    """币种主数据。is_base=TRUE 的即本币（人民币），全系统应恰好一个（service 层守卫）。"""
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO 大写：CNY/USD/HKD…
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # 人民币/美元…
    symbol: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ¥/$…
    is_base: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExchangeRate(UUIDPK, TimestampMixin, Base):
    """汇率表。取值规则：from/to + rate_type 下 effective_date <= 业务日的最近一条（最近不未来）。"""
    __tablename__ = "exchange_rates"

    from_currency: Mapped[str] = mapped_column(String(10), nullable=False)  # 外币（如 USD）
    to_currency: Mapped[str] = mapped_column(String(10), nullable=False)    # 目标币（通常 CNY）
    rate_type: Mapped[str] = mapped_column(String(20), nullable=False, default="中间价")
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)   # 1 外币 = rate 元目标币
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)   # 央行/中行/手工…


class ExchangeGainLossRule(UUIDPK, TimestampMixin, Base):
    """汇兑损益科目规则：场景 → EBS 总账科目码（W11-12 设备分摊 / 三期过账用，本阶段先建配置）。"""
    __tablename__ = "exchange_gain_loss_rules"

    scenario: Mapped[str] = mapped_column(String(50), nullable=False)       # 收款核销/付款核销/期末重估…
    gl_account_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
