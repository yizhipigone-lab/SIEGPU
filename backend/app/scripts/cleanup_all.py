"""整库业务数据清空：删除所有业务数据 + 主数据 + 审计日志。

与 cleanup_demo.py（只清演示项目）/ cleanup_e2e.py（只清 e2e 残留）不同，
本脚本是**全量清空**——用于用户要求"所有数据、包括手工创建的数据都清空"的场景。

保留（不碰）
------------
- users                    登录账号（清空后仍可登录系统）
- workflow_templates       工作流模板（预置配置）
- notifications            用户站内通知
- assistant_*              智能助手会话/消息/认知（5 张表）
- doc_number_rules         单据编号规则（系统配置）
- alembic_version          迁移版本（绝不能动）

清空（TRUNCATE，其余全部业务/主数据表）
--------------------------------------
projects / contracts / orders / sales_orders / devices / assets / capital_transactions /
capital_allocations / leasing_processes / leasing_nodes / leasing_disbursements /
repayments / long_term_payables / off_balance_registers / funding_replacements /
acceptance_records / delivery_stages / billings / invoices / service_confirmations /
revenue_recognitions / profit_scenarios / project_workflows / step_audit_logs /
batch_devices / sales_batch_devices / device_stages / prepayments / payment_requests /
payment_settlements / approvals / contract_amendments / contract_terminations /
return_orders / return_order_devices / insurance_policies / insurance_policy_devices /
ebs_sync_logs / customers / suppliers / equipment_models / banks / audit_logs

实现要点
--------
- FK 全无 CASCADE。siegpu 是 docker postgres 超级用户 → SET session_replication_role = replica
  关 FK 触发器，可安全 DELETE 明确列出的表清单。
- 用 DELETE 而非 TRUNCATE：TRUNCATE 的 FK 引用检查不受 replica 角色屏蔽，
  DELETE 走 FK 触发器、可被 replica 角色放行（与 cleanup_demo.py 已验证做法一致）。
- 幂等：重复执行仍正常。

用法
----
.. code-block:: bash

   docker compose exec backend python -m app.scripts.cleanup_all
"""
from sqlalchemy import text

from app.core.db import SessionLocal

# —— 要清空的表（业务数据 + 主数据 + 审计日志）——
_DELETE_TABLES = [
    # 项目/合同/订单主链路
    "projects", "contracts", "orders", "sales_orders",
    "contract_amendments", "contract_terminations",
    "delivery_stages", "acceptance_records",
    # 设备层
    "devices", "device_stages", "batch_devices", "sales_batch_devices", "assets",
    "off_balance_registers",
    # 资金
    "capital_transactions", "capital_allocations",
    # 金租/还款/去付
    "leasing_processes", "leasing_nodes", "leasing_disbursements",
    "repayments", "long_term_payables", "funding_replacements",
    # 计费/发票/确认/收入
    "billings", "invoices", "service_confirmations", "revenue_recognitions",
    # 盈利/工作流实例
    "profit_scenarios", "project_workflows", "step_audit_logs",
    # 付款/预付款
    "payment_requests", "payment_settlements", "approvals", "prepayments",
    # 退货
    "return_orders", "return_order_devices",
    # 保险
    "insurance_policies", "insurance_policy_devices",
    # EBS 同步日志
    "ebs_sync_logs",
    # 主数据
    "customers", "suppliers", "equipment_models", "banks",
    # 审计日志
    "audit_logs",
]


def _count(db, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def purge_all(db) -> dict:
    """清空全部业务/主数据/审计日志。返回各表清空前行数。

    用 DELETE 而非 TRUNCATE：TRUNCATE 的 FK 引用检查不受
    session_replication_role=replica 屏蔽（会因 insurance_configs→suppliers 等报错），
    DELETE 走 FK 触发器、可被 replica 角色放行。与 cleanup_demo.py 一致。
    """
    db.execute(text("SET session_replication_role = replica"))
    stats: dict[str, int] = {}
    for t in _DELETE_TABLES:
        stats[t] = _count(db, t)
        db.execute(text(f"DELETE FROM {t}"))
    db.execute(text("SET session_replication_role = origin"))
    db.commit()
    return stats


def main() -> None:
    db = SessionLocal()
    before = {
        "projects": _count(db, "projects"),
        "customers": _count(db, "customers"),
        "suppliers": _count(db, "suppliers"),
        "users(保留)": _count(db, "users"),
        "workflow_templates(保留)": _count(db, "workflow_templates"),
    }
    print("[cleanup_all] BEFORE:", before)

    stats = purge_all(db)
    total = sum(stats.values())
    print(f"[cleanup_all] TRUNCATED {len(stats)} tables, {total} rows total:")
    for t, n in stats.items():
        if n:
            print(f"   {t}: {n}")

    after = SessionLocal()
    print("[cleanup_all] AFTER projects:", _count(after, "projects"),
          "customers:", _count(after, "customers"),
          "users(保留):", _count(after, "users"),
          "workflow_templates(保留):", _count(after, "workflow_templates"))
    after.close()


if __name__ == "__main__":
    main()
