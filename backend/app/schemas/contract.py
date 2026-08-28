from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# 二期 W3-4：收入核算路径判定输入/结果枚举（与 contracts CHECK 一致）
PricingAuthority = Literal["自主定价", "客户定价", "上游定价"]
InventoryRiskBearer = Literal["我方", "客户", "上游"]
PrincipalRole = Literal["主要责任人", "代理人"]
RevenueMethod = Literal["总额法", "净额法", "经营租赁", "服务费", "待判定"]
# 四期 W4：合同业务类型——销售侧（算力租赁/转售/服务）
BizType = Literal["算力租赁", "转售", "服务"]
# 缺陷#7：采购侧业务类型独立枚举——与销售口径分开（设备/服务/金租融资）
PurchaseBizType = Literal["设备采购", "服务采购", "金租融资"]


class LineItemIn(BaseModel):
    """缺陷#8：合同明细行入参（行级税率）。"""
    name: str = Field(min_length=1, max_length=200)
    qty: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal = Field(ge=0)  # 单价（不含税）
    tax_rate: Decimal = Field(default=Decimal("0.13"), ge=0, lt=1)
    notes: str | None = None


class ContractLineItemOut(BaseModel):
    id: UUID
    contract_id: UUID
    seq: int
    name: str
    qty: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_amount: Decimal
    line_tax: Decimal
    line_amount_incl: Decimal
    notes: str | None
    model_config = {"from_attributes": True}


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
    leasing_mode: Literal["自有", "直租", "售后回租"] | None = None  # 合同模式快照
    # 二期 W3-4：核算判定信息（可选；SALES 且项目已填 business_type 时保存即自动判定）
    pricing_authority: PricingAuthority | None = None
    inventory_risk_bearer: InventoryRiskBearer | None = None
    principal_role: PrincipalRole | None = None
    # 二期 W5-6：外币合同（currency_code NULL=人民币；booked_rate=签约日记账汇率）
    currency_code: str | None = None
    booked_rate: Decimal | None = Field(None, gt=0)
    # 二期 W9-10：合同深化（全可选）
    purchase_type: str | None = None
    delivery_terms: str | None = None
    warranty_terms: str | None = None
    penalty_terms: str | None = None
    prepayment_ratio: Decimal | None = Field(None, ge=0)
    collection_account_type: Literal["监管户", "一般户"] | None = None
    # 四期 W4：合同类型 / 含税总额 / 算力租赁租期（全可选；amount 仍为不含税）
    biz_type: BizType | None = None
    # 缺陷#7：PURCHASE 侧业务类型（设备采购/服务采购/金租融资），与销售侧分开
    purchase_biz_type: PurchaseBizType | None = None
    amount_incl_tax: Decimal | None = Field(None, ge=0)  # 合同金额（含税）
    lease_months: int | None = Field(None, ge=1)  # 租期(月)，仅算力租赁
    # 缺陷#8：多行明细（行级税率）。有明细行时金额/税率由行合计派生，忽略手填值
    line_items: list[LineItemIn] | None = None


class ContractUpdate(BaseModel):
    """合同编辑（二期 W3-4 新增 PATCH）：金额/类型/项目等核心字段不可改，仅可改下列字段。"""
    contract_no: str | None = None
    monthly_rent: Decimal | None = Field(None, ge=0)
    start_date: date | None = None
    end_date: date | None = None
    file_path: str | None = None
    leasing_mode: Literal["自有", "直租", "售后回租"] | None = None
    pricing_authority: PricingAuthority | None = None
    inventory_risk_bearer: InventoryRiskBearer | None = None
    principal_role: PrincipalRole | None = None
    currency_code: str | None = None
    booked_rate: Decimal | None = Field(None, gt=0)
    purchase_type: str | None = None
    delivery_terms: str | None = None
    warranty_terms: str | None = None
    penalty_terms: str | None = None
    prepayment_ratio: Decimal | None = Field(None, ge=0)
    collection_account_type: Literal["监管户", "一般户"] | None = None
    # 四期 W4：分类/条款/税率/金额可改（不含税随含税联动或直接改；合同变更仍走 Amendment 留痕渠道）
    biz_type: BizType | None = None
    purchase_biz_type: PurchaseBizType | None = None
    tax_rate: Decimal | None = Field(None, ge=0, lt=1)  # 税率（小数，0~1）
    amount_incl_tax: Decimal | None = Field(None, ge=0)
    amount: Decimal | None = Field(None, ge=0)  # 不含税金额（前端由含税自动算/可手改）
    lease_months: int | None = Field(None, ge=1)
    # 缺陷#9：修改对方主体（服务层守门：主体须存在 + 无发票/计费下游才允许改）
    party_id: UUID | None = None
    # 缺陷#8：明细行整组替换（服务层守门：已开票合同禁改行）
    line_items: list[LineItemIn] | None = None


class MethodConfirmIn(BaseModel):
    """人工覆盖/确认核算路径（原因必填，记 audit + confirmed 留痕）。"""
    method: RevenueMethod
    reason: str = Field(min_length=1)


class JudgePreviewOut(BaseModel):
    """判定预览（纯函数，不落库）：前端表单实时预览用。"""
    method: str | None
    rule: str
    basis: str


# ------------------------------ 二期 W9-10：合同变更/终止 ------------------------------

class AmendmentIn(BaseModel):
    change_type: Literal["金额变更", "月租变更", "期限变更", "其他"]
    amendment_date: date | None = None  # 缺省 = 今天（端点填）
    reason: str = Field(min_length=1)  # 变更原因必填（留痕）
    new_amount: Decimal | None = Field(None, ge=0)
    new_monthly_rent: Decimal | None = Field(None, ge=0)
    new_end_date: date | None = None


class AmendmentOut(BaseModel):
    id: UUID
    contract_id: UUID
    amendment_date: date
    change_type: str
    before_json: dict | None
    after_json: dict | None
    reason: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class TerminationIn(BaseModel):
    termination_date: date | None = None  # 缺省 = 今天
    reason: str | None = None
    settlement_note: str | None = None


class TerminationOut(BaseModel):
    id: UUID
    contract_id: UUID
    termination_date: date
    reason: str | None
    settlement_note: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


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
    parent_contract_no: str | None = None  # 参照合同编号（list 时瞬态附加，展示用）
    status: str
    file_path: str | None = None
    leasing_mode: str | None = None
    # 二期 W3-4：核算判定快照
    pricing_authority: str | None = None
    inventory_risk_bearer: str | None = None
    principal_role: str | None = None
    revenue_method: str | None = None
    method_judge_basis: str | None = None
    method_confirmed_by: UUID | None = None
    method_confirmed_at: datetime | None = None
    currency_code: str | None = None
    booked_rate: Decimal | None = None
    purchase_type: str | None = None
    delivery_terms: str | None = None
    warranty_terms: str | None = None
    penalty_terms: str | None = None
    prepayment_ratio: Decimal | None = None
    collection_account_type: str | None = None
    # 四期 W4：合同类型 / 含税总额 / 算力租赁租期
    biz_type: str | None = None
    purchase_biz_type: str | None = None
    amount_incl_tax: Decimal | None = None
    lease_months: int | None = None
    # 缺陷#8：多行明细（行级税率）；无明细行时为空列表
    line_items: list["ContractLineItemOut"] = Field(default_factory=list, exclude=False)
    referenced_purchase_count: int | None = None
    model_config = {"from_attributes": True}
