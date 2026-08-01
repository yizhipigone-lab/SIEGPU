"""资金置换 — Pydantic schemas。"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class FundingReplacementOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    leasing_process_id: uuid.UUID
    original_txn_id: uuid.UUID
    replacement_txn_id: uuid.UUID
    amount: Decimal
    source_type_replaced: str
    replacement_date: date
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
