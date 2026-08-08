"""初始化全部 5 个角色账号（密码统一 sie123）。

upsert：已存在则重置密码/角色/显示名（保留原 id，不破坏外键引用），不存在则创建。
compose 起来后执行：docker compose exec backend python -m app.seed
"""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.user import User

import os
PASSWORD = os.getenv("SEED_PASSWORD", "sie123")
ACCOUNTS = [
    ("admin", "管理员", "ADMIN"),
    ("cfo", "财务总监", "FINANCE_DIRECTOR"),
    ("buyer", "采购对接人", "PROCUREMENT"),
    ("delivery", "项目交付负责人", "DELIVERY"),
    ("finance", "财务专员", "FINANCE_STAFF"),
]


def seed() -> None:
    db = SessionLocal()
    try:
        for username, display, role in ACCOUNTS:
            existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
            if existing:
                existing.password_hash = hash_password(PASSWORD)
                existing.display_name = display
                existing.role = role
                existing.active = True
                tag = "reset"
            else:
                db.add(User(
                    username=username, display_name=display,
                    password_hash=hash_password(PASSWORD), role=role, active=True,
                ))
                tag = "created"
            print(f"  {username}/{PASSWORD} ({role}) — {tag}")
        db.commit()
    finally:
        db.close()


def seed_templates():
    """预置向导式工作流模板（按 name 幂等：缺哪个补哪个，便于增量加模板自愈）。"""
    from app.core.db import SessionLocal as SL
    from app.services.workflow_service import _default_steps, _device_flow_steps
    from app.services.workflow_template_service import create_template, list_templates
    db = SL()
    try:
        by_name = {t.name: t for t in list_templates(db, active_only=False)}
        changed = []

        # 模板1: 标准金租 18 步
        if "标准金租流程（18步）" not in by_name:
            create_template(db, name="标准金租流程（18步）",
                description="完整链路：自有+流贷垫付→金租置换，覆盖项目建立到盈利测算全流程",
                steps=_default_steps())
            changed.append("标准18步（新建）")

        # 模板2: 自有资金全款 15 步（跳过 Step 6/9/10）。独立调 _default_steps 避免与 18 步共享 dict 引用。
        if "自有资金全款流程（15步）" not in by_name:
            steps_15 = [s for s in _default_steps() if s["seq"] not in (6, 9, 10)]
            for i, s in enumerate(steps_15, 1):  # 重新编号 seq
                s["seq"] = i
            create_template(db, name="自有资金全款流程（15步）",
                description="精简版：跳过银行流贷和金租环节，自有资金直接采购→交付→运营",
                steps=steps_15)
            changed.append("自有全款15步（新建）")

        # 模板3: 设备粒度 7 节点（一期 W3-4，W7-8 起 11 步）。completion_check 指向 device_stages/devices。
        # 代码即真相（upsert）：create_workflow 按 copy.deepcopy(tmpl.steps) 复制【已落地模板】，
        # 故 _device_flow_steps 演进（W7-8 插金租放款步）必须回写已落地模板，否则首次 seed 冻结的旧 steps
        # 会被原样复制（亲历：pytest 直调函数=11 步绿，e2e HTTP 路径复制旧模板=10 步红）。
        # 10步→11步就地改名（同一行 id，project_workflows.template_id FK 不破）。
        DF_NEW = "设备粒度流程（11步·device-flow-7stage）"
        DF_OLD = "设备粒度流程（10步·device-flow-7stage）"
        df_steps = _device_flow_steps()
        df_tmpl = by_name.get(DF_NEW) or by_name.get(DF_OLD)
        if df_tmpl is None:
            create_template(db, name=DF_NEW,
                description="单台设备粒度：批次订单→设备导入→7节点推进（到货/上架/点亮验收）→金租放款→按台计费",
                steps=df_steps)
            changed.append("设备粒度11步（新建）")
        elif df_tmpl.name != DF_NEW or df_tmpl.steps != df_steps:
            df_tmpl.name = DF_NEW
            df_tmpl.description = "单台设备粒度：批次订单→设备导入→7节点推进（到货/上架/点亮验收）→金租放款→按台计费"
            df_tmpl.steps = df_steps
            changed.append("设备粒度11步（刷新）")

        if changed:
            db.commit()
            print(f"  向导模板同步：{', '.join(changed)}")
        else:
            print(f"  模板已是最新（{len(by_name)} 个），跳过")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    seed_templates()
