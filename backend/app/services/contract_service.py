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


def _check_purchase_cap(db: Session, *, parent: Contract, this_incl, exclude_id=None,
                        this_is_financing: bool = False) -> None:
    """采购总额硬校验：同销售合同下所有采购合同金额合计（排除 exclude_id 自身）+ 本份 ≤ 销售合同额。

    缺陷#10：金租融资合同（purchase_biz_type='金租融资'）不计入额度池——
    设备款在「设备采购」合同已占用额度，金租合同是融资行为（本金对应设备款），
    双计会把合法的"设备采购+金租"组合顶爆。金租合同自身也免校验。
    """
    if this_is_financing:
        return  # 金租融资合同：融资行为，不占采购额度池
    cap = _incl_amount(parent)
    if cap is None:
        return
    # 逐行 COALESCE(amount_incl_tax, amount)：含税为 NULL 的兄弟合同退回不含税口径；
    # 豁免兄弟行里的金租融资合同（缺陷#10 双计修复）
    q = select(func.coalesce(func.sum(func.coalesce(Contract.amount_incl_tax, Contract.amount)), 0)) \
        .where(Contract.parent_contract_id == parent.id,
               Contract.deleted_at.is_(None),
               func.coalesce(Contract.purchase_biz_type, "") != "金租融资")
    if exclude_id is not None:
        q = q.where(Contract.id != exclude_id)
    siblings = db.execute(q).scalar() or Decimal("0")
    if Decimal(str(siblings)) + Decimal(str(this_incl)) > Decimal(str(cap)):
        raise BusinessError(
            "AMOUNT_EXCEEDED",
            f"超过销售合同额度：已用 {siblings} + 本份 {this_incl} > 销售额 {cap}",
            400,
        )


def create_contract(db: Session, *, project_id, type: str, party_id, amount,
                    tax_rate, monthly_rent=None, contract_no=None, start_date=None,
                    end_date=None, parent_contract_id=None, file_path=None,
                    leasing_mode=None, pricing_authority=None, inventory_risk_bearer=None,
                    principal_role=None, currency_code=None, booked_rate=None, actor_id=None,
                    purchase_type=None, delivery_terms=None, warranty_terms=None,
                    penalty_terms=None, prepayment_ratio=None, collection_account_type=None,
                    biz_type=None, amount_incl_tax=None, lease_months=None,
                    purchase_biz_type=None, line_items=None) -> Contract:
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
        # 缺陷#7：采购合同类型归属校验——biz_type 是销售口径，采购侧应填 purchase_biz_type
        if biz_type is not None and purchase_biz_type is None:
            purchase_biz_type = {"转售": "设备采购", "服务": "服务采购"}.get(biz_type)
    # 缺陷#8：明细行汇总覆盖合同级金额（amount/amount_incl_tax/tax_rate 由行合计派生）
    if line_items:
        from app.services.contract_line_service import summarize_line_items
        amount, amount_incl_tax, tax_rate = summarize_line_items(line_items)
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
        # 总额硬校验（缺陷#10：金租融资豁免额度池）
        _check_purchase_cap(db, parent=parent,
                            this_incl=(amount_incl_tax if amount_incl_tax is not None else amount),
                            this_is_financing=(purchase_biz_type == "金租融资"))
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
        purchase_biz_type=purchase_biz_type,
    )
    db.add(c)
    db.flush()
    # 缺陷#8：明细行落库（行级税率）
    if line_items:
        from app.services.contract_line_service import persist_line_items
        persist_line_items(db, c.id, line_items)
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
               "biz_type", "amount_incl_tax", "tax_rate", "lease_months", "amount",
               # 缺陷#7：采购侧业务类型；缺陷#9：未做下游单据时允许改对方主体
               "purchase_biz_type", "party_id")


def _check_party_change(db: Session, c: Contract, new_party_id) -> None:
    """缺陷#9：修改对方主体的守门校验。

    1. 新主体必须存在且与合同方向匹配（SALES→客户，PURCHASE→供应商）；
    2. 未产生下游单据（发票/计费）才允许改——有开票/计费的合同改主体会造成勾稽断裂。
    """
    from app.models.billing import Billing, Invoice
    if c.type == "SALES":
        if not db.get(Customer, new_party_id):
            raise BusinessError("BAD_REQUEST", "销售合同的对方必须是已存在的客户", 400)
    else:
        if not db.get(Supplier, new_party_id):
            raise BusinessError("BAD_REQUEST", "采购合同的对方必须是已存在的供应商", 400)
    has_invoice = db.execute(
        select(Invoice.id).where(Invoice.contract_id == c.id,
                                 Invoice.deleted_at.is_(None)).limit(1)
    ).first()
    has_billing = db.execute(
        select(Billing.id).where(Billing.contract_id == c.id,
                                 Billing.deleted_at.is_(None)).limit(1)
    ).first()
    if has_invoice or has_billing:
        raise BusinessError(
            "STATE_ERROR",
            "该合同已有发票或计费单，不能修改对方主体（避免勾稽断裂）；"
            "请先红冲相关单据后再改",
            409,
        )


def update_contract(db: Session, cid, *, actor_id=None, **fields) -> Contract:
    """编辑合同（白名单字段）+ 保存后重判（同创建门槛）。"""
    c = get_contract_or_404(db, cid)
    # 缺陷#9：修改对方主体（party_id）→ 存在性 + 下游单据守门
    if fields.get("party_id") is not None and fields["party_id"] != c.party_id:
        _check_party_change(db, c, fields["party_id"])
    # C1 修复：编辑采购合同金额（amount / amount_incl_tax）时同样做总额硬校验，排除自身
    if c.type == "PURCHASE" and c.parent_contract_id \
            and any(fields.get(k) is not None for k in ("amount", "amount_incl_tax")):
        new_incl_tax = fields["amount_incl_tax"] if fields.get("amount_incl_tax") is not None else c.amount_incl_tax
        new_amount = fields["amount"] if fields.get("amount") is not None else c.amount
        this_incl = new_incl_tax if new_incl_tax is not None else new_amount
        # 缺陷#10：金租融资合同编辑金额同样豁免额度校验
        fin = fields.get("purchase_biz_type") or c.purchase_biz_type
        if this_incl is not None:
            parent = db.get(Contract, c.parent_contract_id)
            if parent is not None and parent.deleted_at is None:
                _check_purchase_cap(db, parent=parent, this_incl=this_incl, exclude_id=c.id,
                                    this_is_financing=(fin == "金租融资"))
    for k, v in fields.items():
        if k in _UPDATEABLE and v is not None:
            setattr(c, k, v)
    # 缺陷#8：明细行整组替换（全量删旧插新；无下游发票时才允许改行）
    if fields.get("line_items") is not None:
        from app.services.contract_line_service import persist_line_items, summarize_line_items
        from app.models.billing import Invoice
        has_invoice = db.execute(
            select(Invoice.id).where(Invoice.contract_id == c.id,
                                     Invoice.deleted_at.is_(None)).limit(1)
        ).first()
        if has_invoice:
            raise BusinessError("STATE_ERROR", "该合同已开票，不能修改明细行；请先红冲发票", 409)
        persist_line_items(db, c.id, fields["line_items"])
        c.amount, c.amount_incl_tax, c.tax_rate = summarize_line_items(fields["line_items"])
    db.flush()
    from app.services import revenue_judge_service as _judge
    if _judge.should_auto_judge(db, c):
        _judge.judge_and_record(db, c, actor_id=actor_id)
    # 销售合同金额/条款变更后：提示其下被参照的采购合同数（前端据此提示复核）
    if c.type == "SALES":
        from sqlalchemy import func
        cnt = db.execute(
            select(func.count(Contract.id)).where(
                Contract.parent_contract_id == c.id,
                Contract.deleted_at.is_(None),
            )
        ).scalar() or 0
        c.referenced_purchase_count = cnt  # 瞬态属性，仅本次响应携带，不落库
    return c


def list_contracts(db: Session, project_id=None, type=None, parent_contract_id=None):
    stmt = select(Contract).order_by(Contract.created_at.desc())
    if project_id:
        stmt = stmt.where(Contract.project_id == project_id)
    if type:
        stmt = stmt.where(Contract.type == type)
    if parent_contract_id:
        stmt = stmt.where(Contract.parent_contract_id == parent_contract_id)
    rows = db.execute(stmt).scalars().all()
    # 附加 parent_contract_no（展示用瞬态属性，批量查一次避免 N+1）
    parent_ids = {r.parent_contract_id for r in rows if r.parent_contract_id}
    if parent_ids:
        parents = {p.id: p for p in db.execute(select(Contract).where(Contract.id.in_(parent_ids))).scalars().all()}
        for r in rows:
            p = parents.get(r.parent_contract_id)
            r.parent_contract_no = p.contract_no if p else None
    return rows


def get_contract_or_404(db: Session, cid) -> Contract:
    c = db.get(Contract, cid)
    if not c or c.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "合同不存在", 404)
    return c
