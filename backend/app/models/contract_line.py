"""合同明细行（缺陷#8：多行内容/多税率录入）。

背景：一份合同可能同时含多个税率——天璇算力服务 6% + 末期买断 13%；
金租售后回租本金 13% + 利息 6%。原 contracts 单 tax_rate 字段无法表达。

设计：
- contract_line_items 挂 contract_id，行级 name/qty/unit_price(不含税)/tax_rate/备注；
- 行金额 = qty * unit_price（不含税），税额 = 行金额 * 行税率，行价税合计落库存快照；
- contracts.amount / amount_incl_tax / tax_rate 仍为冗余汇总口径：有明细行时
  amount=Σ行不含税、amount_incl_tax=Σ行价税合计、tax_rate=加权平均（展示用）；
  开票/计费按行走（invoice_service 取行级税率拆票）。
- 明细行全删 = 回退单税率模式（amount/tax_rate 手填仍有效）。
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class ContractLineItem(UUIDPK, TimestampMixin, Base):
    __tablename__ = "contract_line_items"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 行号 1..N
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # 内容名称（如：算力服务费/设备买断款）
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("1"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 单价（不含税）
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.13"), nullable=False)
    line_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 不含税金额 = qty*unit_price
    line_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 税额 = line_amount*tax_rate
    line_amount_incl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # 价税合计
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
