"""合同明细行服务（缺陷#8：多行内容/多税率录入）。

- summarize_line_items：纯函数汇总（不含税合计/价税合计/加权税率），不碰 DB
- persist_line_items：全量删旧插新（编辑即整组替换）
- load_line_items：批量读取（list/detail 接口附加，避免 N+1）
"""
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.contract_line import ContractLineItem


class LineItemIn:
    """入参结构（由 schema 传入 dict 列表：name/qty/unit_price/tax_rate/notes）。"""


def summarize_line_items(items: list) -> tuple[Decimal, Decimal, Decimal]:
    """返回 (不含税合计, 价税合计, 加权平均税率)。

    加权税率 = Σ税额 / Σ不含税（展示口径；开票按行级税率走，不用这个平均数）。
    """
    total_amt = Decimal("0")
    total_incl = Decimal("0")
    for it in items:
        qty = Decimal(str(it.get("qty", 1) or 1))
        unit = Decimal(str(it.get("unit_price", 0) or 0))
        rate = Decimal(str(it.get("tax_rate", 0.13) or 0))
        amt = (qty * unit).quantize(Decimal("0.01"))
        total_amt += amt
        total_incl += (amt * (1 + rate)).quantize(Decimal("0.01"))
    avg_rate = (total_incl - total_amt) / total_amt if total_amt else Decimal("0")
    return total_amt, total_incl, avg_rate


def persist_line_items(db: Session, contract_id, items: list) -> int:
    """全量替换：删旧插新。items 为 dict 列表（pydantic .model_dump() 后）。返回行数。"""
    db.execute(delete(ContractLineItem).where(ContractLineItem.contract_id == contract_id))
    rows = []
    for i, it in enumerate(items, 1):
        qty = Decimal(str(it.get("qty", 1) or 1))
        unit = Decimal(str(it.get("unit_price", 0) or 0))
        rate = Decimal(str(it.get("tax_rate", 0.13) or 0))
        amt = (qty * unit).quantize(Decimal("0.01"))
        tax = (amt * rate).quantize(Decimal("0.01"))
        rows.append(ContractLineItem(
            contract_id=contract_id, seq=i,
            name=it.get("name") or f"明细行{i}",
            qty=qty, unit_price=unit, tax_rate=rate,
            line_amount=amt, line_tax=tax, line_amount_incl=amt + tax,
            notes=it.get("notes"),
        ))
    if rows:
        db.add_all(rows)
    db.flush()
    return len(rows)


def load_line_items(db: Session, contract_ids: list) -> dict:
    """批量读取：{contract_id: [ContractLineItem...]}（按 seq 升序）。"""
    if not contract_ids:
        return {}
    rows = db.execute(
        select(ContractLineItem)
        .where(ContractLineItem.contract_id.in_(contract_ids))
        .order_by(ContractLineItem.contract_id, ContractLineItem.seq)
    ).scalars().all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.contract_id, []).append(r)
    return out
