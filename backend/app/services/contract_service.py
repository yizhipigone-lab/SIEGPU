"""合同服务。type 决定 direction 与 party_type（SALES→RECEIVABLE/customer，PURCHASE→PAYABLE/supplier）。"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.master import Customer, Supplier
from app.models.project import Project
from app.models.project import Contract


def _incl_amount(c) -> Decimal | None:
    """合同的对比口径金额：优先含税 amount_incl_tax，NULL 退回不含税 amount。"""
    if c.amount_incl_tax is not None:
        return c.amount_incl_tax
    return c.amount


def create_contract(db: Session, *, project_id, type: str, party_id, amount,
                    tax_rate, monthly_rent=None, contract_no=None, start_date=None,
                    end_date=None, parent_contract_id=None, file_path=None,
                    leasing_mode=None, pricing_authority=None, inventory_risk_bearer=None,
                    principal_role=None, currency_code=None, booked_rate=None, actor_id=None,
                    purchase_type=None, delivery_terms=None, warranty_terms=None,
                    penalty_terms=None, prepayment_ratio=None, collection_account_type=None,
                    biz_type=None, amount_incl_tax=None, lease_months=None) -> Contract:
    proj = db.get(Project, project_id)
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    direction = "RECEIVABLE" if type == "SALES" else "PAYABLE"
    party_type = "customer" if type == "SALES" else "supplier"
    # 校验 party 存在且类型匹配
    if type == "SALES":
        if not db.get(Customer, party_id):
            raise BusinessError("BAD_REQUEST", "销售合同的 party 必须是已存在的客户", 400)
    else:
        sup = db.get(Supplier, party_id)
        if not sup:
            raise BusinessError("BAD_REQUEST", "采购合同的 party 必须是已存在的供应商", 400)
    # 采购合同必须参照同项目的一份销售合同（1 销售 : N 采购，创建后锁定）
    if type == "PURCHASE":
        if not parent_contract_id:
            raise BusinessError("BAD_REQUEST", "采购合同必须选择参照的销售合同", 400)
        parent = db.get(Contract, parent_contract_id)
        if not parent or parent.deleted_at is not None:
            raise BusinessError("BAD_REQUEST", "参照的销售合同不存在", 400)
        if parent.project_id != project_id:
            raise BusinessError("BAD_REQUEST", "参照的销售合同必须属于本项目", 400)
        if parent.type != "SALES":
            raise BusinessError("BAD_REQUEST", "参照合同必须是销售合同", 400)
        # 总额硬校验：同销售合同下所有采购合同金额合计 + 本份 ≤ 销售合同额（同侧口径）
        cap = _incl_amount(parent)
        if cap is not None:
            # 逐行 COALESCE(amount_incl_tax, amount)：含税为 NULL 的兄弟合同退回不含税口径
            siblings = db.execute(
                select(func.coalesce(func.sum(func.coalesce(Contract.amount_incl_tax, Contract.amount)), 0))
                .where(Contract.parent_contract_id == parent.id)
                .where(Contract.deleted_at.is_(None))
            ).scalar() or Decimal("0")
            this_incl = amount_incl_tax if amount_incl_tax is not None else amount
            if Decimal(str(siblings)) + Decimal(str(this_incl)) > Decimal(str(cap)):
                raise BusinessError(
                    "AMOUNT_EXCEEDED",
                    f"超过销售合同额度：已用 {siblings} + 本份 {this_incl} > 销售额 {cap}",
                    400,
                )
    c = Contract(
        project_id=project_id, contract_no=contract_no, type=type, party_type=party_type,
        party_id=party_id, direction=direction, amount=amount, tax_rate=tax_rate,
        monthly_rent=monthly_rent, start_date=start_date, end_date=end_date,
        parent_contract_id=parent_contract_id, file_path=file_path, status="已签",
        leasing_mode=leasing_mode,
        pricing_authority=pricing_authority, inventory_risk_bearer=inventory_risk_bearer,
        principal_role=principal_role, currency_code=currency_code, booked_rate=booked_rate,
        purchase_type=purchase_type, delivery_terms=delivery_terms, warranty_terms=warranty_terms,
        penalty_terms=penalty_terms, prepayment_ratio=prepayment_ratio,
        collection_account_type=collection_account_type,
        biz_type=biz_type, amount_incl_tax=amount_incl_tax, lease_months=lease_months,
    )
    db.add(c)
    db.flush()
    from app.services import workflow_service as _wf
    _wf.after_action(db, project_id)
    # 二期 W3-4：保存即判定（仅 SALES 且有判定上下文；无上下文保持 NULL，旧流程零变化）
    from app.services import revenue_judge_service as _judge
    if _judge.should_auto_judge(db, c):
        _judge.judge_and_record(db, c, actor_id=actor_id)
    return c


# 二期 W3-4：合同编辑可改字段白名单（金额/类型/项目等核心字段不可改）
_UPDATEABLE = ("contract_no", "monthly_rent", "start_date", "end_date", "file_path",
               "leasing_mode", "pricing_authority", "inventory_risk_bearer", "principal_role",
               "currency_code", "booked_rate", "purchase_type", "delivery_terms",
               "warranty_terms", "penalty_terms", "prepayment_ratio", "collection_account_type",
               # 四期 W4：合同类型 / 含税总额 / 税率 / 租期 / 不含税金额（金额随含税联动，保存即生效）
               "biz_type", "amount_incl_tax", "tax_rate", "lease_months", "amount")


def update_contract(db: Session, cid, *, actor_id=None, **fields) -> Contract:
    """编辑合同（白名单字段）+ 保存后重判（同创建门槛）。"""
    c = get_contract_or_404(db, cid)
    for k, v in fields.items():
        if k in _UPDATEABLE and v is not None:
            setattr(c, k, v)
    db.flush()
    from app.services import revenue_judge_service as _judge
    if _judge.should_auto_judge(db, c):
        _judge.judge_and_record(db, c, actor_id=actor_id)
    return c


def list_contracts(db: Session, project_id=None, type=None):
    stmt = select(Contract).order_by(Contract.created_at.desc())
    if project_id:
        stmt = stmt.where(Contract.project_id == project_id)
    if type:
        stmt = stmt.where(Contract.type == type)
    return db.execute(stmt).scalars().all()


def get_contract_or_404(db: Session, cid) -> Contract:
    c = db.get(Contract, cid)
    if not c or c.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "合同不存在", 404)
    return c
