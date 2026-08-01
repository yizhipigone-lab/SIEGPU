from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class InvoiceCreate(BaseModel):
    contract_id: UUID
    invoice_no: str | None = None
    amount: Decimal = Field(ge=0)  # 含税
    issue_date: date | None = None
    due_date: date | None = None
    file_path: str | None = None


class InvoiceOut(BaseModel):
    id: UUID
    contract_id: UUID
    direction: str
    invoice_no: str | None
    amount: Decimal
    amount_ex_tax: Decimal
    tax_amount: Decimal
    issue_date: date | None
    due_date: date | None
    paid_date: date | None
    status: str
    model_config = {"from_attributes": True}


class MarkPaid(BaseModel):
    paid_date: date


class ReconRow(BaseModel):
    contract_id: UUID
    contract_amount: Decimal
    billed: Decimal
    invoiced: Decimal
    received: Decimal
    gap_billed: Decimal
    gap_invoiced: Decimal
