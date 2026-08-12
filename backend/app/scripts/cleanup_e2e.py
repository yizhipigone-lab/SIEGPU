"""dev-DB e2e 测试数据清理（一次性清旧污染 + 每次 e2e 跑完由 globalTeardown 调用）。

为什么需要它
------------
e2e 无测试隔离，每次跑都往共享 dev-DB 造数据。``seed.py`` 只建用户 + 工作流模板，
**不建任何业务实体**，故凡 e2e 造的项目 / 客户 / 供应商 / 设备 / 合同 / 发票 / 通知都是测试残留。

历史教训（2026-08-09 一期终审）：``capital-flow.spec.ts`` 曾硬编码 ``'E2E-商机5090'``
（无 RUN 后缀），每跑积一条，最终堆出 99 条「采购待办」工作流（step2 进行中）。
``get_my_tasks`` 无 LIMIT 全量加载，全量并发下请求超时被前端吞成空列表
（``Dashboard.vue`` ``myTasks.value = t.data || []``），导致 ``wizard-workspace.spec.ts``
的 a1（采购待办卡）间歇性看到「暂无轮到你的步骤」→ 全套 flake。

判据（只删「明确是 e2e 产物」的，保留手工 demo 数据）
----------------------------------------------------
============================  ============================================  ========================================
表                             删除条件（正则）                               保留的手工 demo 数据
============================  ============================================  ========================================
projects                       ``^(E2E-|DC-PROJ|DBG-PROJ)``                 商机5090(全链路演示)、HTTP防双计*
customers                      ``^(E2E客户|客户-F|客户-E2E)``                TY科技(庭宇)、客户hbh*
suppliers                      ``^(E2E供应商|DBG-SUP|DC-SUP|金租-(LB|DIS|CLS)-)``  宽恒设备、远东金租
equipment_models               ``^(E2E-|M-F2|DBG-EQ|DC-EQ|H100-|RTX-)``     5090算力服务器
devices (sn)                   ``^GPU-``                                     ——
contracts (contract_no)        ``^HT-F``                                     ——
invoices (invoice_no)          ``^INV-``                                     ——
notifications (body)           ``E2E-F1-``                                   ——
ebs_field_mappings (ebs_field) ``^E2E_``                                     ——（二期 W1-2 新表）
ebs_sync_logs (entity_id)      e2e 客户集合（``客户-E2E``）                   ——（二期 W1-2 新表）
============================  ============================================  ========================================

实现要点
--------
- FK 全无 CASCADE。``siegpu`` 是 docker postgres 超级用户 → ``SET session_replication_role = replica``
  临时关 FK 触发器，可不按依赖序删除；个别残留的「孤立子行」无害（``get_my_tasks`` 遇
  project 缺失即 ``continue``，[workflow_service.py:141](app/services/workflow_service.py)）。
- 反射 ``Base.metadata.tables``：凡有 ``project_id`` 列的表，按 e2e 项目集合批量删 ——
  覆盖所有挂在 e2e 项目下的子表，无需手维护表清单。
- 幂等：重复执行命中 0 行也正常。

用法
----
.. code-block:: bash

   docker compose exec backend python -m app.scripts.cleanup_e2e
"""
from sqlalchemy import bindparam, text

from app.core.db import SessionLocal
import app.models  # noqa: F401  注册全部模型到 Base.metadata（反射 project_id 列需要）
from app.models.base import Base

# —— 各表独立判据（避免误伤手工 demo 数据）——
_PROJ_RE = r"^(E2E-|DC-PROJ|DBG-PROJ)"
_CUST_RE = r"^(E2E客户|客户-F|客户-E2E)"
_SUP_RE = r"^(E2E供应商|DBG-SUP|DC-SUP|金租-(LB|DIS|CLS)-)"
_EQ_RE = r"^(E2E-|M-F2|DBG-EQ|DC-EQ|H100-|RTX-)"

# 独立按编号/内容删（不依赖项目关联的表）
_STANDALONE = [
    ("devices", "sn", r"^GPU-"),
    ("contracts", "contract_no", r"^HT-F"),
    ("invoices", "invoice_no", r"^INV-"),
    ("notifications", "body", r"E2E-F1-"),
]


def _count(db, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def purge_e2e(db) -> dict:
    """删除 dev-DB 的 e2e 测试数据。返回各表删除条数（供打印/断言）。"""
    # siegpu 是 docker postgres 超级用户 → 切 replication 角色绕开 FK 触发器
    db.execute(text("SET session_replication_role = replica"))

    deleted: dict[str, int] = {}

    # 1) 凡有 project_id 列的表：按 e2e 项目集合删（覆盖所有挂在 e2e 项目下的子表）
    proj_ids = [r[0] for r in db.execute(
        text("SELECT id FROM projects WHERE name ~ :re"), {"re": _PROJ_RE}
    )]
    deleted["projects(matched)"] = len(proj_ids)
    if proj_ids:
        # expanding bindparam：IN (:id_0, :id_1, ...)，驱动无关、稳。
        for tbl_name, tbl in Base.metadata.tables.items():
            if "project_id" in tbl.columns:
                stmt = text(f"DELETE FROM {tbl_name} WHERE project_id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                )
                res = db.execute(stmt, {"ids": proj_ids})
                deleted[f"{tbl_name}(by_project)"] = res.rowcount

    # 2) e2e 项目本身（子行已清或被 replication 角子放行）
    res = db.execute(text("DELETE FROM projects WHERE name ~ :re"), {"re": _PROJ_RE})
    deleted["projects"] = res.rowcount

    # 3) 独立按编号/内容删（设备/合同/发票/通知）
    for tbl, col, pat in _STANDALONE:
        res = db.execute(text(f"DELETE FROM {tbl} WHERE {col} ~ :re"), {"re": pat})
        deleted[tbl] = res.rowcount

    # 4) 二期 W1-2 EBS：清测试字段映射（按 ebs_field 前缀 E2E_ 标记）+ 同步日志
    #    （按 e2e 客户集合；entity_id 是 text，子查询须在客户被删前执行）
    res = db.execute(text("DELETE FROM ebs_field_mappings WHERE ebs_field ~ :re"), {"re": r"^E2E_"})
    deleted["ebs_field_mappings"] = res.rowcount
    res = db.execute(text(
        "DELETE FROM ebs_sync_logs WHERE entity_id IN (SELECT id::text FROM customers WHERE name ~ :re)"
    ), {"re": _CUST_RE})
    deleted["ebs_sync_logs"] = res.rowcount

    # 5) 主数据（客户/供应商/型号）—— 引用它们的子表已清，可安全删
    for tbl, col, pat in [("customers", "name", _CUST_RE),
                          ("suppliers", "name", _SUP_RE),
                          ("equipment_models", "name", _EQ_RE)]:
        res = db.execute(text(f"DELETE FROM {tbl} WHERE {col} ~ :re"), {"re": pat})
        deleted[tbl] = res.rowcount

    db.execute(text("SET session_replication_role = origin"))
    db.commit()
    return deleted


def _procurement_todo_count(db) -> int:
    """采购待办数 = step2 进行中的工作流。这就是压垮 wizard a1 的那个数。"""
    return db.execute(text(
        "SELECT count(*) FROM project_workflows WHERE current_step=2 AND status='进行中'"
    )).scalar_one()


def main() -> None:
    db = SessionLocal()
    before = {
        "projects": _count(db, "projects"),
        "project_workflows": _count(db, "project_workflows"),
        "procurement_todos(step2)": _procurement_todo_count(db),
        "customers": _count(db, "customers"),
        "suppliers": _count(db, "suppliers"),
        "devices": _count(db, "devices"),
    }
    print("[cleanup_e2e] BEFORE:", before)

    deleted = purge_e2e(db)
    print("[cleanup_e2e] DELETED:", deleted)

    after = SessionLocal()
    after_todo = _procurement_todo_count(after)
    print("[cleanup_e2e] AFTER procurement_todos(step2):", after_todo,
          "projects:", _count(after, "projects"))
    after.close()


if __name__ == "__main__":
    main()
