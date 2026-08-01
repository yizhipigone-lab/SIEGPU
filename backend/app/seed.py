"""初始化全部 5 个角色账号（密码统一 sie123）。

upsert：已存在则重置密码/角色/显示名（保留原 id，不破坏外键引用），不存在则创建。
compose 起来后执行：docker compose exec backend python -m app.seed
"""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.user import User

PASSWORD = "sie123"
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


if __name__ == "__main__":
    seed()
