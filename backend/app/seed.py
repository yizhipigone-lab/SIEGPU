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
    """预置向导式工作流模板。"""
    from app.core.db import SessionLocal as SL
    from app.services.workflow_service import _default_steps
    from app.services.workflow_template_service import create_template, list_templates
    db = SL()
    try:
        existing = list_templates(db, active_only=False)
        if existing:
            print(f"  模板已存在 ({len(existing)} 个)，跳过")
            return

        # 模板1: 标准金租 18 步
        steps_18 = _default_steps()
        create_template(db, name="标准金租流程（18步）",
            description="完整链路：自有+流贷垫付→金租置换，覆盖项目建立到盈利测算全流程",
            steps=steps_18)

        # 模板2: 自有资金全款 15 步（跳过 Step 6/9/10）
        steps_15 = [s for s in steps_18 if s["seq"] not in (6, 9, 10)]
        # 重新编号 seq
        for i, s in enumerate(steps_15, 1):
            s["seq"] = i
        create_template(db, name="自有资金全款流程（15步）",
            description="精简版：跳过银行流贷和金租环节，自有资金直接采购→交付→运营",
            steps=steps_15)

        db.commit()
        print("  向导模板已预置：标准18步 / 自有全款15步")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    seed_templates()
