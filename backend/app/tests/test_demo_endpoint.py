"""新手引导专项：一键载入演示项目端点（权限守卫 + 幂等）。

demo.run() 是全链路造数（需 cfo 用户 + 完整 schema），不适合单测里真跑；
这里测端点本身的守门逻辑：非管理角色 403、演示项目已存在时 loaded=False 不重复造数。
"""
import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.demo import DEMO_CODE, load_demo
from app.core.deps import require_role
from app.models.project import Project
from app.models.user import User


def _user(role: str) -> User:
    return User(username="t", display_name="t", password_hash="x", role=role, active=True)


def test_demo_load_requires_admin_role():
    dep = require_role("ADMIN", "FINANCE_DIRECTOR")
    # 普通财务专员被拒
    with pytest.raises(HTTPException) as ei:
        dep(user=_user("FINANCE_STAFF"))
    assert ei.value.status_code == 403
    # 管理员 / 财务总监放行
    assert dep(user=_user("ADMIN")).role == "ADMIN"
    assert dep(user=_user("FINANCE_DIRECTOR")).role == "FINANCE_DIRECTOR"


def test_demo_load_skips_when_exists(db):
    admin = _user("ADMIN")
    db.add(admin)
    db.flush()
    db.add(Project(name="x", code=DEMO_CODE))
    db.flush()

    r = load_demo(db=db, user=admin)
    assert r["loaded"] is False
    assert "已存在" in r["message"]
