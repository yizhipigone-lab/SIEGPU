"""演示数据清理脚本 purge_demo 的删除范围与误删防护测试。

red/green 靶子：验证 purge_demo 只删 DEMO-5090 项目及其专属主数据，
绝不误伤手工录入项目/主数据（spec 的最高优先级）。
"""
from datetime import date
from decimal import Decimal

from app.models.capital import CapitalTransaction
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.project import Contract, Project
from app.scripts.cleanup_demo import purge_demo


def _seed(db):
    """造最小 demo 数据 + 手工对照数据，返回 (demo_project_id, real_project_id)。"""
    # 专属主数据（demo 牵出，应被删）
    cust_demo = Customer(name="TY科技(庭宇)")
    sup_kuanheng = Supplier(name="宽恒设备", type="设备供应商")
    sup_yuandong = Supplier(name="远东金租", type="资金供应商")
    eq_demo = EquipmentModel(name="5090算力服务器", category="大卡")
    bank_demo = Bank(name="工商银行")
    # 手工主数据（不应被删）
    cust_real = Customer(name="真实客户甲")
    sup_real = Supplier(name="真实供应商乙", type="设备供应商")
    db.add_all([cust_demo, sup_kuanheng, sup_yuandong, eq_demo, bank_demo,
                cust_real, sup_real])
    db.flush()

    # demo 项目 + 子表行（带 project_id）
    demo = Project(name="商机5090(全链路演示)", code="DEMO-5090",
                   total_investment=Decimal("830060000"))
    # 手工项目（不应被删）
    real = Project(name="真实项目", code="REAL-001")
    db.add_all([demo, real])
    db.flush()

    db.add(Contract(project_id=demo.id, type="SALES", party_type="customer",
                    party_id=cust_demo.id, direction="RECEIVABLE",
                    amount=Decimal("100"), contract_no="S-5090"))
    db.add(Contract(project_id=real.id, type="SALES", party_type="customer",
                    party_id=cust_real.id, direction="RECEIVABLE",
                    amount=Decimal("50"), contract_no="S-REAL"))
    db.add(CapitalTransaction(project_id=demo.id, source_type="银行流贷",
                              direction="IN", amount=Decimal("10"),
                              transaction_date=date(2026, 4, 5)))
    db.add(CapitalTransaction(project_id=real.id, source_type="银行流贷",
                              direction="IN", amount=Decimal("5"),
                              transaction_date=date(2026, 4, 5)))
    db.flush()
    return demo.id, real.id


def test_purge_demo_deletes_project_and_children(db):
    demo_id, real_id = _seed(db)

    deleted = purge_demo(db, project_id=demo_id)

    # demo 项目及其带 project_id 的子表归零
    assert deleted["projects"] == 1
    assert deleted["contracts(by_project)"] == 1
    assert deleted["capital_transactions(by_project)"] == 1
    # 手工项目与子表保留
    assert db.get(Project, real_id) is not None
    from sqlalchemy import select, func
    assert db.execute(select(func.count()).select_from(Contract)
                      .where(Contract.project_id == real_id)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(CapitalTransaction)
                      .where(CapitalTransaction.project_id == real_id)).scalar_one() == 1
    # demo 项目本身已删
    assert db.get(Project, demo_id) is None


def test_purge_demo_deletes_demo_master_data_only(db):
    demo_id, _ = _seed(db)
    purge_demo(db, project_id=demo_id)

    from sqlalchemy import select
    names = {n for (n,) in db.execute(select(Customer.name))}
    assert "TY科技(庭宇)" not in names
    assert "真实客户甲" in names  # 手工客户保留
    sup_names = {n for (n,) in db.execute(select(Supplier.name))}
    assert "宽恒设备" not in sup_names and "远东金租" not in sup_names
    assert "真实供应商乙" in sup_names
    assert "工商银行" not in {n for (n,) in db.execute(select(Bank.name))}
    assert "5090算力服务器" not in {n for (n,) in db.execute(select(EquipmentModel.name))}


def test_purge_demo_idempotent_when_missing(db):
    deleted = purge_demo(db, project_id=None)  # 无 demo 项目时
    assert deleted["projects"] == 0
