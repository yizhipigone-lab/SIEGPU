"""操作留痕查询端点测试：权限守卫 + 按实体过滤 + 用户显示名解析。"""
import uuid

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.audit import list_audit
from app.core.deps import require_role
from app.models.user import AuditLog, User


def _user(db, role="ADMIN") -> User:
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="审计员", password_hash="x", role=role, active=True)
    db.add(u)
    db.flush()
    return u


def test_list_audit_requires_admin_role():
    dep = require_role("ADMIN", "FINANCE_DIRECTOR")
    with pytest.raises(HTTPException) as ei:
        dep(user=_user_without_db("FINANCE_STAFF"))
    assert ei.value.status_code == 403
    assert dep(user=_user_without_db("ADMIN")).role == "ADMIN"
    assert dep(user=_user_without_db("FINANCE_DIRECTOR")).role == "FINANCE_DIRECTOR"


def _user_without_db(role: str) -> User:
    return User(username="t", display_name="t", password_hash="x", role=role, active=True)


def test_list_audit_filters_by_entity_and_resolves_user(db):
    u = _user(db)
    eid = uuid.uuid4()
    db.add(AuditLog(user_id=u.id, action="UPDATE", entity_type="contract", entity_id=eid, after_json={"amount": 1}))
    db.add(AuditLog(user_id=u.id, action="UPDATE", entity_type="order", entity_id=uuid.uuid4()))
    db.flush()

    r = list_audit(entity_type="contract", entity_id=str(eid), limit=50, db=db, user=u)
    assert len(r["items"]) == 1
    assert r["items"][0]["action"] == "UPDATE"
    assert r["items"][0]["user_name"] == "审计员"
    # 精简返回：不再回传 before/after JSON（前端只用 action/user/时间）
    assert "before_json" not in r["items"][0]
    assert "after_json" not in r["items"][0]


def test_list_audit_bad_entity_id_returns_empty(db):
    u = _user(db)
    r = list_audit(entity_type="contract", entity_id="not-a-uuid", limit=50, db=db, user=u)
    assert r["items"] == []
