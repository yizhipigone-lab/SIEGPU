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
    if inv.status in ("已收票", "已回款", "已付款", "已核销"):
        raise BusinessError("DUPLICATE", "发票已标记收款/付款", 409)
    inv.paid_date = paid_date
    # v3.1 发票池状态：销售→已回款，采购→已付款
    inv.status = "已回款" if inv.direction == "RECEIVABLE" else "已付款"
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
    from app.services import audit_service as _audit
    _audit.log(db, user_id=reversed_by, action="REVERSE", target_type="invoice",
               target_id=inv.id, after_json={"reversal_id": str(rev.id), "amount": str(inv.amount)})
    return inv, rev


# —— v3.1 发票池 + 核销 ——

def pool_query(db: Session, *, direction: str | None = None,
               status: str | None = None, contract_id=None,
               skip=0, limit=100) -> list[Invoice]:
    """发票池统一查询。"""
    stmt = select(Invoice).where(Invoice.deleted_at.is_(None))
    if direction:
        stmt = stmt.where(Invoice.direction == direction)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if contract_id:
        stmt = stmt.where(Invoice.contract_id == contract_id)
    stmt = stmt.order_by(Invoice.created_at.desc()).offset(skip).limit(limit)
    return db.execute(stmt).scalars().all()


def reconcile_invoice(db: Session, *, invoice_id, txn_id,
                      reconciled_by) -> Invoice:
    """逐笔核销：将一笔发票与一笔资金流水匹配勾销。

    支持部分核销——多次调用逐步累加直到覆盖发票全额。
    全部匹配后自动置 reconciled_at。
    """
    from app.models.capital import CapitalTransaction

    inv = db.get(Invoice, invoice_id)
    if not inv or inv.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "发票不存在", 404)
    if inv.status == "已红冲":
        raise BusinessError("BAD_REQUEST", "已红冲发票不可核销", 400)
    if inv.status == "已核销":
        raise BusinessError("DUPLICATE", "发票已核销", 409)

    txn = db.get(CapitalTransaction, txn_id)
    if not txn or txn.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "资金流水不存在", 404)

    # 方向校验：销售发票→收款流水(IN)，采购发票→付款流水(OUT)
    if inv.direction == "RECEIVABLE" and txn.direction != "IN":
        raise BusinessError("VALIDATION_ERROR", "销售发票只能核销收款流水(IN)", 422)
    if inv.direction == "PAYABLE" and txn.direction != "OUT":
        raise BusinessError("VALIDATION_ERROR", "采购发票只能核销付款流水(OUT)", 422)
    if txn.invoice_id and txn.invoice_id != inv.id:
        raise BusinessError("DUPLICATE", "该流水已关联其他发票", 409)

    # 回填关联
    txn.invoice_id = inv.id
    inv.capital_transaction_id = txn_id

    # 检查是否全部匹配：Σ已关联流水金额 >= 发票金额
    matched = db.execute(
        select(func.coalesce(func.sum(CapitalTransaction.amount), 0)).where(
            CapitalTransaction.invoice_id == inv.id, CapitalTransaction.deleted_at.is_(None))
    ).scalar() or Decimal(0)

    if matched >= inv.amount:
        inv.status = "已核销"
        inv.reconciled_at = func.now()
        inv.reconciled_by = reconciled_by

    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=reconciled_by, action="RECONCILE", target_type="invoice",
               target_id=inv.id, after_json={"amount": str(inv.amount), "matched": str(matched)})
    from app.services import workflow_service as _wf
    c = db.get(Contract, inv.contract_id)
    if c:
        _wf.after_action(db, c.project_id)
    return inv
