from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.invoice import InvoiceCreate, InvoiceOut, MarkPaid
from app.services import invoice_service as svc
from app.services import pdf_service

router = APIRouter()


@router.get("")
def list_invoices(contract_id: UUID | None = None, direction: str | None = None,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_invoices(db, contract_id=contract_id, direction=direction)
    return {"items": [InvoiceOut.model_validate(i).model_dump(mode="json") for i in rows], "total": len(rows)}


@router.post("", response_model=InvoiceOut, status_code=201)
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    inv = svc.create_invoice(
        db, contract_id=payload.contract_id, amount=payload.amount, invoice_no=payload.invoice_no,
        issue_date=payload.issue_date, due_date=payload.due_date, file_path=payload.file_path,
    )
    db.commit()
    return InvoiceOut.model_validate(inv)


@router.post("/{invoice_id}/pay", response_model=InvoiceOut)
def mark_paid(invoice_id: UUID, payload: MarkPaid, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    inv = svc.mark_paid(db, invoice_id, payload.paid_date)
    db.commit()
    return InvoiceOut.model_validate(inv)


@router.get("/reconciliation")
def reconciliation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.reconciliation(db)}


@router.post("/{invoice_id}/reverse")
def reverse(invoice_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    inv, rev = svc.reverse_invoice(db, invoice_id=invoice_id, reversed_by=user.id)
    db.commit()
    return {"invoice_id": str(inv.id), "status": inv.status, "reversal_id": str(rev.id)}


@router.get("/{invoice_id}/pdf")
def invoice_pdf(invoice_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """F4：发票/账单 PDF 实时生成（不落库，浏览器直接下载）。"""
    buf = pdf_service.render_invoice_pdf(db, invoice_id)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{invoice_id}.pdf"'},
    )


# —— v3.1 发票池 + 核销 ——

@router.get("/pool")
def invoice_pool(direction: str | None = None, status: str | None = None,
                 contract_id: UUID | None = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    rows = svc.pool_query(db, direction=direction, status=status, contract_id=contract_id)
    return {"items": [InvoiceOut.model_validate(i).model_dump(mode="json") for i in rows], "total": len(rows)}


@router.post("/{invoice_id}/reconcile/{txn_id}")
def reconcile_inv(invoice_id: UUID, txn_id: UUID,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    inv = svc.reconcile_invoice(db, invoice_id=invoice_id, txn_id=txn_id, reconciled_by=user.id)
    db.commit()
    return InvoiceOut.model_validate(inv).model_dump(mode="json")
