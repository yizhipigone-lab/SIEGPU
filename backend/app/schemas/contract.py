from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ContractCreate(BaseModel):
    project_id: UUID
    contract_no: str | None = None
    type: Literal["SALES", "PURCHASE"]
    party_id: UUID  # SALES→客户；PURCHASE→供应商
    amount: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=Decimal("0.13"), ge=0, lt=1)
    monthly_rent: Decimal | None = Field(None, ge=0)  # SALES 含税月租（计费用）
    start_date: date | None = None
    end_date: date | None = None
    parent_contract_id: UUID | None = None
    file_path: str | None = None


class ContractOut(BaseModel):
    id: UUID
    project_id: UUID
    contract_no: str | None
    type: str
    party_type: str
    party_id: UUID
    direction: str
    amount: Decimal
    tax_rate: Decimal
    monthly_rent: Decimal | None
    start_date: date | None
    end_date: date | None
    parent_contract_id: UUID | None
    status: str
    file_path: str | None = None
    model_config = {"from_attributes": True}
