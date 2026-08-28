"""dev-DB 演示数据清理：删除「商机5090 全链路演示」项目(DEMO-5090)牵出的全部数据。

与 cleanup_e2e.py 对称，但判据锁定 demo 项目（保留手工录入的真实业务数据）。

为什么需要它
------------
「一键载入演示项目」(Dashboard 按钮) 会 POST /demo/load → 调 demo.py run()，落库一整套
商机5090 全链路数据（项目/合同/订单/资金流水/金租/还款/验收/交付/计费/发票/确认单/盈利场景/工作流）。
用户测试完想清空演示数据时，需要一套精确、幂等、不误伤手工数据的清理脚本。

数据血缘（全部以 project_id=DEMO-5090 为根）：
- 凡含 project_id 列的表：直接按项目 id 删（反射 Base.metadata.tables，无需手维护表清单）
- 无 project_id、靠外键挂接的子表：先在「子表被级联删」前按子查询扫孤儿行或按父表 id 删
  （见下方 _CHILD_QUERIES，覆盖：devices/资产占位、金租/还款、设备层、退还、保险分摊等）

实现要点
--------
- FK 全无 CASCADE。siegpu 是 docker postgres 超级用户 → SET session_replication_role = replica
  临时关 FK 触发器，可不按依赖序删除；个别残留孤立子行无害（同 cleanup_e2e 已验证）。
- 幂等：重复执行命中 0 行也正常。

用法
----
.. code-block:: bash

   docker compose exec backend python -m app.scripts.cleanup_demo
"""
from sqlalchemy import bindparam, text

from app.core.db import SessionLocal
import app.models  # noqa: F401  注册全部模型到 Base.metadata
from app.models.base import Base

DEMO_CODE = "DEMO-5090"

# —— demo 专属主数据（引用它们的业务子表清完后可安全删）——
_DEMO_CUSTOMERS = "TY科技(庭宇)"
_DEMO_SUPPLIERS = ("宽恒设备", "远东金租")
_DEMO_EQUIPMENT = "5090算力服务器"
_DEMO_BANK = "工商银行"


def _count(db, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def purge_demo(db, project_id=None) -> dict:
    """删除 demo 项目及其关联数据。返回各表删除条数。"""
    db.execute(text("SET session_replication_role = replica"))

    if project_id is None:
        project_id = db.execute(text(
            "SELECT id FROM projects WHERE code = :c"), {"c": DEMO_CODE}
        ).scalar_one_or_none()

    deleted: dict[str, int] = {}

    if project_id is None:
        db.execute(text("SET session_replication_role = origin"))
        deleted["projects"] = 0
        return deleted

    # 1) demo 牵出的订单/销售订单/合同/金租流程 —— 无 project_id 的父级 id 集合
    order_ids = [r[0] for r in db.execute(text(
        "SELECT id FROM orders WHERE project_id = :pid"), {"pid": project_id})]
    sales_order_ids = [r[0] for r in db.execute(text(
        "SELECT id FROM sales_orders WHERE project_id = :pid"), {"pid": project_id})]
    contract_ids = [r[0] for r in db.execute(text(
        "SELECT id FROM contracts WHERE project_id = :pid"), {"pid": project_id})]
    leasing_ids = [r[0] for r in db.execute(text(
        "SELECT id FROM leasing_processes WHERE project_id = :pid"), {"pid": project_id})]
    invoice_ids = []
    if contract_ids:
        stmt = text("SELECT id FROM invoices WHERE contract_id IN :cids").bindparams(
            bindparam("cids", expanding=True))
        invoice_ids = [r[0] for r in db.execute(stmt, {"cids": contract_ids})]
    billing_ids = [r[0] for r in db.execute(text(
        "SELECT id FROM billings WHERE project_id = :pid"), {"pid": project_id})]

    # 2) 凡有 project_id 列的表：按 demo 项目 id 删（覆盖所有挂项目下的子表）
    for tbl_name, tbl in Base.metadata.tables.items():
        if "project_id" in tbl.columns:
            stmt = text(f"DELETE FROM {tbl_name} WHERE project_id = :pid")
            res = db.execute(stmt, {"pid": project_id})
            deleted[f"{tbl_name}(by_project)"] = res.rowcount

    # 3) 无 project_id、靠外键挂接的子表（父表在第 2 步已被删，先按父 id 集合删子行）
    #    统一用 IN :ids + expanding（与 cleanup_e2e 已验证写法一致）
    def _del_by_ids(tbl: str, col: str, ids: list, tag: str) -> None:
        if not ids:
            return
        stmt = text(f"DELETE FROM {tbl} WHERE {col} IN :ids").bindparams(
            bindparam("ids", expanding=True))
        res = db.execute(stmt, {"ids": ids})
        deleted[f"{tbl}({tag})"] = res.rowcount

    _del_by_ids("delivery_stages", "order_id", order_ids, "by_order")
    for tbl, col in [("leasing_nodes", "process_id"),
                     ("leasing_disbursements", "process_id"),
                     ("repayments", "leasing_process_id"),
                     ("off_balance_registers", "leasing_process_id"),
                     ("long_term_payables", "leasing_process_id")]:
        _del_by_ids(tbl, col, leasing_ids, "by_leasing")
    _del_by_ids("service_confirmations", "sales_order_id", sales_order_ids, "by_sales_order")
    for tbl, col in [("revenue_recognitions", "contract_id"),
                     ("payment_requests", "contract_id"),
                     ("prepayments", "contract_id"),
                     ("contract_amendments", "contract_id"),
                     ("contract_terminations", "contract_id")]:
        _del_by_ids(tbl, col, contract_ids, "by_contract")
    _del_by_ids("payment_settlements", "invoice_id", invoice_ids, "by_invoice")
    _del_by_ids("revenue_recognitions", "invoice_id", invoice_ids, "by_invoice")
    _del_by_ids("service_confirmations", "billing_id", billing_ids, "by_billing")

    # 4) 项目本身（子行已清或被 replication 角色放行）
    res = db.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})
    deleted["projects"] = res.rowcount

    # 5) 无 project_id 但挂 demo 数据下的孤儿子表（父已删后扫）
    cleared_invoices = invoice_ids
    if cleared_invoices:
        for tbl, col in [("payment_settlements", "invoice_id"),
                         ("revenue_recognitions", "invoice_id")]:
            stmt = text(f"DELETE FROM {tbl} WHERE {col} IN :ids").bindparams(
                bindparam("ids", expanding=True))
            res = db.execute(stmt, {"ids": cleared_invoices})
            deleted[f"{tbl}(by_invoice)"] = res.rowcount
    if billing_ids:
        res = db.execute(text(
            "DELETE FROM service_confirmations WHERE billing_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)), {"ids": billing_ids})
        deleted["service_confirmations(by_billing)"] = res.rowcount

    # 6) 设备层孤儿（demo light_on 只建 asset 不建 device，一般 0 行；兜底扫孤儿）
    res = db.execute(text(
        "DELETE FROM device_stages WHERE device_id NOT IN (SELECT id FROM devices)"))
    deleted["device_stages(orphan)"] = res.rowcount
    res = db.execute(text(
        "DELETE FROM batch_devices WHERE device_id NOT IN (SELECT id FROM devices)"))
    deleted["batch_devices(orphan)"] = res.rowcount
    res = db.execute(text(
        "DELETE FROM sales_batch_devices WHERE device_id NOT IN (SELECT id FROM devices)"))
    deleted["sales_batch_devices(orphan)"] = res.rowcount
    res = db.execute(text(
        "DELETE FROM insurance_policy_devices WHERE policy_id NOT IN (SELECT id FROM insurance_policies)"))
    deleted["insurance_policy_devices(orphan)"] = res.rowcount
    res = db.execute(text(
        "DELETE FROM return_order_devices WHERE return_order_id NOT IN (SELECT id FROM return_orders)"))
    deleted["return_order_devices(orphan)"] = res.rowcount

    # 7) demo 专属主数据（客户/供应商/型号/银行）
    res = db.execute(text("DELETE FROM customers WHERE name = :n"),
                     {"n": _DEMO_CUSTOMERS})
    deleted["customers"] = res.rowcount
    for name in _DEMO_SUPPLIERS:
        res = db.execute(text("DELETE FROM suppliers WHERE name = :n"), {"n": name})
        deleted[f"suppliers.{name}"] = res.rowcount
    res = db.execute(text("DELETE FROM equipment_models WHERE name = :n"),
                     {"n": _DEMO_EQUIPMENT})
    deleted["equipment_models"] = res.rowcount
    res = db.execute(text("DELETE FROM banks WHERE name = :n"), {"n": _DEMO_BANK})
    deleted["banks"] = res.rowcount

    db.execute(text("SET session_replication_role = origin"))
    db.commit()
    return deleted


def main() -> None:
    db = SessionLocal()
    before = {
        "projects": _count(db, "projects"),
        "contracts": _count(db, "contracts"),
        "orders": _count(db, "orders"),
        "customers": _count(db, "customers"),
        "suppliers": _count(db, "suppliers"),
        "equipment_models": _count(db, "equipment_models"),
        "banks": _count(db, "banks"),
    }
    print("[cleanup_demo] BEFORE:", before)

    deleted = purge_demo(db)
    print("[cleanup_demo] DELETED:", deleted)

    after = SessionLocal()
    print("[cleanup_demo] AFTER projects:", _count(after, "projects"),
          "customers:", _count(after, "customers"),
          "suppliers:", _count(after, "suppliers"))
    after.close()


if __name__ == "__main__":
    main()
