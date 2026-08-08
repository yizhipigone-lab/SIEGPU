"""合同服务。type 决定 direction 与 party_type（SALES→RECEIVABLE/customer，PURCHASE→PAYABLE/supplier）。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.master import Customer, Supplier
from app.models.project import Project
from app.models.project import Contract


def create_contract(db: Session, *, project_id, type: str, party_id, amount,
                    tax_rate, monthly_rent=None, contract_no=None, start_date=None,
                    end_date=None, parent_contract_id=None, file_path=None,
                    leasing_mode=None) -> Contract:
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
    c = Contract(
        project_id=project_id, contract_no=contract_no, type=type, party_type=party_type,
        party_id=party_id, direction=direction, amount=amount, tax_rate=tax_rate,
        monthly_rent=monthly_rent, start_date=start_date, end_date=end_date,
        parent_contract_id=parent_contract_id, file_path=file_path, status="已签",
        leasing_mode=leasing_mode,
    )
    db.add(c)
    db.flush()
    from app.services import workflow_service as _wf
    _wf.after_action(db, project_id)
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
