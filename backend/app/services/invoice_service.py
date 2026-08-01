"""发票服务（§5.6）：CRUD + 三流对账 + 超开拦截。"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, InvoiceOverContract
from app.models.billing import Billing, Invoice
from app.models.project import Contract
from app.utils.reconcile import is_over_contract, q2

from .contract_service import get_contract_or_404


def create_invoice(db: Session, *, contract_id, amount: Decimal, invoice_no=None,
                   issue_date=None, due_date=None, paid_date=None, file_path=None) -> Invoice:
    c = get_contract_or_404(db, contract_id)
    ex, tax = _split(amount, c.tax_rate)
    # 超开拦截：Σ已有不含税 + 新增不含税 > 合同额 × (1 + tolerance)
    existing = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_ex_tax), 0)).where(
            Invoice.contract_id == contract_id, Invoice.direction == c.direction,
            Invoice.status != "已红冲",
        )
    ).scalar() or Decimal(0)
    if is_over_contract(existing_ex_tax_sum=existing, new_ex_tax=ex, contract_amount_ex_tax=c.amount):
        raise InvoiceOverContract(contract_amount=c.amount, invoiced_after=existing + ex)

    inv = Invoice(
        contract_id=contract_id, direction=c.direction, invoice_no=invoice_no, amount=amount,
        amount_ex_tax=ex, tax_amount=tax, tax_rate=c.tax_rate, issue_date=issue_date, due_date=due_date,
        paid_date=paid_date, status="已开", file_path=file_path,
    )
    db.add(inv)
    db.flush()
    return inv


def list_invoices(db: Session, contract_id=None, direction=None):
    stmt = select(Invoice).order_by(Invoice.issue_date.desc())
    if contract_id:
        stmt = stmt.where(Invoice.contract_id == contract_id)
    if direction:
        stmt = stmt.where(Invoice.direction == direction)
    return db.execute(stmt).scalars().all()


def mark_paid(db: Session, invoice_id, paid_date) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "发票不存在", 404)
    if inv.status in ("已收票", "已付款"):
        raise BusinessError("DUPLICATE", "发票已标记收款/付款", 409)
    inv.paid_date = paid_date
    inv.status = "已收票" if inv.direction == "RECEIVABLE" else "已付款"
    db.flush()
    return inv


def reconciliation(db: Session) -> list[dict]:
    """三流对账（收端，按销售合同）：合同额 vs 应收(计费) vs 已开票 vs 已收款。"""
    rows = []
    for c in db.execute(select(Contract).where(Contract.type == "SALES")).scalars():
        billed = db.execute(
            select(func.coalesce(func.sum(Billing.amount_ex_tax), 0)).where(
                Billing.contract_id == c.id, Billing.status != "已红冲")
        ).scalar() or Decimal(0)
        invoiced = db.execute(
            select(func.coalesce(func.sum(Invoice.amount_ex_tax), 0)).where(
                Invoice.contract_id == c.id, Invoice.direction == "RECEIVABLE",
                Invoice.status != "已红冲")
        ).scalar() or Decimal(0)
        received = db.execute(
            select(func.coalesce(func.sum(Invoice.amount), 0)).where(
                Invoice.contract_id == c.id, Invoice.direction == "RECEIVABLE",
                Invoice.paid_date.is_not(None), Invoice.status != "已红冲")
        ).scalar() or Decimal(0)
        rows.append({
            "contract_id": str(c.id), "contract_amount": q2(c.amount),
            "billed": q2(billed), "invoiced": q2(invoiced), "received": q2(received),
            "gap_billed": q2(c.amount - billed), "gap_invoiced": q2(invoiced - received),
        })
    return rows


def _split(amount_incl: Decimal, tax_rate: Decimal):
    # 复用 utils 的价税分离（与 schema CHECK 一致）
    from app.utils.billing import split_tax
    return split_tax(amount_incl, tax_rate)


def reverse_invoice(db: Session, *, invoice_id, reversed_by, note: str = "红冲"):
    """发票红冲：原票置'已红冲'（对账自动剔除），另建红冲凭证记录留痕（reversal_of_id 指向原票）。"""
    from datetime import date as _date

    inv = db.get(Invoice, invoice_id)
    if not inv or inv.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "发票不存在", 404)
    if inv.status == "已红冲":
        raise BusinessError("DUPLICATE", "发票已红冲", 409)
    inv.status = "已红冲"
    rev = Invoice(
        contract_id=inv.contract_id, direction=inv.direction,
        invoice_no=f"红冲-{inv.invoice_no or str(inv.id)}", amount=inv.amount,
        amount_ex_tax=inv.amount_ex_tax, tax_amount=inv.tax_amount, tax_rate=inv.tax_rate,
        issue_date=_date.today(), status="已红冲", reversal_of_id=inv.id,
    )
    db.add(rev)
    db.flush()
    return inv, rev
