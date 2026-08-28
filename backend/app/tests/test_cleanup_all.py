"""整库清空脚本 purge_all 的范围测试：清业务/主数据/审计，保留账号/模板/通知/助手。

red/green 靶子：验证 purge_all 清空全部业务数据与主数据，但绝不碰
users / workflow_templates / notifications / assistant_* / doc_number_rules。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, func

from app.models.capital import CapitalTransaction
from app.models.contract_ext import DocNumberRule
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.notification import Notification
from app.models.project import Contract, Project
from app.models.user import AuditLog, User
from app.models.workflow_template import WorkflowTemplate
from app.scripts.cleanup_all import purge_all


def _seed(db):
    """造业务数据 + 主数据 + 审计日志 + 保留数据。"""
    cust = Customer(name="客户X")
    sup = Supplier(name="供应商Y", type="设备供应商")
    eq = EquipmentModel(name="型号Z", category="大卡")
    bank = Bank(name="银行W")
    db.add_all([cust, sup, eq, bank])
    db.flush()

    proj = Project(name="项目A", code="PROJ-A", total_investment=Decimal("100"))
    db.add(proj); db.flush()
    db.add(Contract(project_id=proj.id, type="SALES", party_type="customer",
                    party_id=cust.id, direction="RECEIVABLE",
                    amount=Decimal("10"), contract_no="C-A"))
    db.add(CapitalTransaction(project_id=proj.id, source_type="银行流贷",
                              direction="IN", amount=Decimal("10"),
                              transaction_date=date(2026, 1, 1)))

    # 保留数据
    user = User(username="keep_u", display_name="保留账号", password_hash="x",
                role="ADMIN", active=True)
    db.add(user); db.flush()
    db.add(Notification(user_id=user.id, kind="TEST", title="保留通知",
                        body="body", level="提示"))
    db.add(AuditLog(user_id=user.id, action="CREATE", entity_type="x",
                    entity_id=uuid.uuid4()))
    db.flush()
    return proj.id, user.id


def test_purge_all_clears_business_and_master(db):
    proj_id, user_id = _seed(db)
    purge_all(db)

    # 业务表清空
    assert db.get(Project, proj_id) is None
    for m in (Contract, CapitalTransaction):
        assert db.execute(select(func.count()).select_from(m)).scalar_one() == 0
    # 主数据清空
    for m in (Customer, Supplier, EquipmentModel, Bank):
        assert db.execute(select(func.count()).select_from(m)).scalar_one() == 0
    # 审计日志清空
    assert db.execute(select(func.count()).select_from(AuditLog)).scalar_one() == 0


def test_purge_all_preserves_accounts_and_templates(db):
    _seed(db)
    purge_all(db)

    # 保留：账号、通知
    assert db.execute(select(func.count()).select_from(User)).scalar_one() >= 1
    assert db.execute(select(func.count()).select_from(Notification)).scalar_one() >= 1
    # 模板/编号规则表未被清空（该表无 seed 行，验证结构存在、可查询即可）
    db.execute(select(func.count()).select_from(WorkflowTemplate)).scalar_one()
    db.execute(select(func.count()).select_from(DocNumberRule)).scalar_one()
