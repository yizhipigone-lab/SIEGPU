from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CurrencyIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)  # ISO 码，service 层归一大写
    name: str = Field(min_length=1, max_length=50)
    symbol: str | None = None
    is_base: bool = False
    active: bool = True


class CurrencyPatch(BaseModel):
    name: str | None = None
    symbol: str | None = None
    is_base: bool | None = None
    active: bool | None = None


class CurrencyOut(BaseModel):
    id: UUID
    code: str
    name: str
    symbol: str | None
    is_base: bool
    active: bool
    model_config = {"from_attributes": True}


class RateIn(BaseModel):
    from_currency: str = Field(min_length=1, max_length=10)
    to_currency: str = Field(min_length=1, max_length=10)
    rate: Decimal = Field(gt=0)  # DECIMAL(18,8) 全精度（D6：率永不 round）
    effective_date: date
    rate_type: str = "中间价"
    source: str | None = None


class RateOut(BaseModel):
    id: UUID
    from_currency: str
    to_currency: str
    rate_type: str
    rate: Decimal
    effective_date: date
    source: str | None
    model_config = {"from_attributes": True}


class RateLookupOut(BaseModel):
    from_currency: str
    to_currency: str
    rate_type: str
    on_date: date
    rate: Decimal


class GlRuleIn(BaseModel):
    scenario: str = Field(min_length=1, max_length=50)
    gl_account_code: str = Field(min_length=1, max_length=50)
    description: str | None = None


class GlRuleOut(BaseModel):
    id: UUID
    scenario: str
    gl_account_code: str
    description: str | None
    model_config = {"from_attributes": True}
