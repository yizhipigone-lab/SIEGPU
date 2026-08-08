"""合同/发票 PDF 生成（F4）测试：返回非空且为合法 PDF，404 用例。"""
import uuid
from datetime import date
from decimal import Decimal

from app.core.exceptions import BusinessError
from app.models.master import Customer
from app.models.project import Project
from app.services import contract_service as csvc
from app.services import invoice_service as invsvc
from app.services import pdf_service


def _setup(db):
    p = Project(name="PDF测试项目", code="c-pdf01")
    db.add(p); db.flush()
    cust = Customer(name="租户PDF"); db.add(cust); db.flush()
    c = csvc.create_contract(
        db, project_id=p.id, type="SALES", party_id=cust.id,
        amount=Decimal("10000"), tax_rate=Decimal("0.13"), monthly_rent=Decimal("1000"),
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), leasing_mode="自有",
    )
    inv = invsvc.create_invoice(
        db, contract_id=c.id, amount=Decimal("5000"),
        invoice_no="INV-PDF-001", issue_date=date(2026, 1, 31), due_date=date(2026, 2, 28),
    )
    return c, inv


def test_contract_pdf_is_valid(db):
    c, _ = _setup(db)
    data = pdf_service.render_contract_pdf(db, c.id).read()
    assert len(data) > 1000              # 非空：真实 PDF 通常几十 KB
    assert data[:4] == b"%PDF"           # 合法 PDF 头


def test_invoice_pdf_is_valid(db):
    _, inv = _setup(db)
    data = pdf_service.render_invoice_pdf(db, inv.id).read()
    assert len(data) > 1000
    assert data[:4] == b"%PDF"


def test_contract_pdf_404(db):
    try:
        pdf_service.render_contract_pdf(db, uuid.uuid4())
        assert False, "合同不存在应抛 404"
    except BusinessError as e:
        assert e.status_code == 404


def test_invoice_pdf_404(db):
    try:
        pdf_service.render_invoice_pdf(db, uuid.uuid4())
        assert False, "发票不存在应抛 404"
    except BusinessError as e:
        assert e.status_code == 404
