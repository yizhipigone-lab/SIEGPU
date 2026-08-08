"""合同/发票 PDF 生成（F4）。

weasyprint + jinja2：HTML/CSS 模板 → PDF。中文由容器内 fonts-noto-cjk 渲染。
PDF 实时生成、不落库（与合同/发票的扫描件 file_path 区分，避免混淆）。
"""
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.core.exceptions import BusinessError
from app.models.billing import Invoice
from app.models.master import Customer, Supplier
from app.models.project import Contract, Project

_TMPL_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TMPL_DIR)), autoescape=select_autoescape())


def _money(d: Decimal | float | int | None) -> str:
    """金额格式化：None → '—'；否则 ￥1,234.56（千分位 + 两位小数）。"""
    if d is None:
        return "—"
    return f"￥{Decimal(d):,.2f}"


def _split_tax(amount: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal]:
    """含税金额拆 不含税 / 税额（均两位小数）。税率为 0 时全额为不含税。"""
    amount = amount or Decimal("0")
    tax_rate = tax_rate or Decimal("0")
    if tax_rate:
        ex = (amount / (1 + tax_rate)).quantize(Decimal("0.01"))
    else:
        ex = amount.quantize(Decimal("0.01"))
    tax = (amount - ex).quantize(Decimal("0.01"))
    return ex, tax


def _party_name(db, party_type: str, party_id) -> str:
    """party_id 多态：customer→Customer.name；supplier→Supplier.name。"""
    if party_type == "customer":
        c = db.get(Customer, party_id)
        return c.name if c else "（客户已删除）"
    s = db.get(Supplier, party_id)
    return s.name if s else "（供应商已删除）"


def render_contract_pdf(db, contract_id) -> BytesIO:
    c = db.get(Contract, contract_id)
    if c is None:
        raise BusinessError("NOT_FOUND", "合同不存在", 404)
    project = db.get(Project, c.project_id)
    party_name = _party_name(db, c.party_type, c.party_id)
    ex_tax, tax_amt = _split_tax(c.amount, c.tax_rate)
    title = "算力设备租赁合同" if c.type == "SALES" else "算力设备采购合同"
    html = _env.get_template("contract.html").render(
        title=title, today=date.today().isoformat(), contract=c, project=project,
        party_name=party_name, money=_money, ex_tax=ex_tax, tax_amt=tax_amt,
    )
    buf = BytesIO()
    HTML(string=html).write_pdf(buf)
    buf.seek(0)
    return buf


def render_invoice_pdf(db, invoice_id) -> BytesIO:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise BusinessError("NOT_FOUND", "发票不存在", 404)
    contract = db.get(Contract, inv.contract_id)
    project = db.get(Project, contract.project_id) if contract else None
    party_name = _party_name(db, contract.party_type, contract.party_id) if contract else "—"
    balance = (inv.amount or Decimal("0")) - (inv.matched_amount or Decimal("0"))
    html = _env.get_template("invoice.html").render(
        today=date.today().isoformat(), invoice=inv, contract=contract, project=project,
        party_name=party_name, money=_money, balance=balance,
    )
    buf = BytesIO()
    HTML(string=html).write_pdf(buf)
    buf.seek(0)
    return buf
