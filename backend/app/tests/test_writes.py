"""写操作确认卡测试（M-C C-5）：dry_run/原子认领/幂等/过期/越权/角色/限额/审计/开关。"""
import datetime as dt
import uuid
from decimal import Decimal

import pytest

from app.models.assistant import AssistantConfirmToken
from app.models.billing import Invoice  # noqa: F401  (确保模型注册)
from app.models.capital import CapitalTransaction
from app.models.project import Project
from app.models.user import AuditLog, User
from app.services.assistant import tools, writes


def _user(db, role="FINANCE_STAFF") -> User:
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="财务", password_hash="x", role=role, active=True)
    db.add(u)
    db.flush()
    return u


def _project(db) -> Project:
    p = Project(name=f"项目{uuid.uuid4().hex[:6]}", status="进行中")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def writes_on(monkeypatch):
    monkeypatch.setattr(writes.settings, "assistant_writes_enabled", True)
    monkeypatch.setattr(writes.settings, "assistant_write_actions", "record_income,advance_step,allocate_funds")
    writes.reset_cache()
    yield
    writes.reset_cache()


class TestDryRun:
    def test_dry_run_no_business_write(self, db, writes_on):
        u, p = _user(db), _project(db)
        before = db.query(CapitalTransaction.id).all()
    def test_amount_must_be_positive(self, db, writes_on):
        u, p = _user(db), _project(db)
        r = writes.dry_run(db, u, "record_income", {"project_name": p.name, "amount": -5})
        assert "error" in r and "大于 0" in r["error"]

    def test_ambiguous_project_rejected(self, db, writes_on):
        u = _user(db)
        _project(db); _project(db)
        r = writes.dry_run(db, u, "record_income", {"project_name": "项目", "amount": 1})
        assert "error" in r and "命中" in r["error"]

    def test_role_gate(self, db, writes_on):
        u, p = _user(db, role="DELIVERY"), _project(db)
        r = writes.dry_run(db, u, "record_income", {"project_name": p.name, "amount": 1})
        assert "error" in r and "角色" in r["error"]

    def test_flag_off_hides_tools(self, db, monkeypatch):
        monkeypatch.setattr(writes.settings, "assistant_writes_enabled", False)
        writes.reset_cache()
        names = [t["function"]["name"] for t in tools.openai_tools()]
        assert not any(n.startswith("request_") for n in names)
        with pytest.raises(KeyError):
            tools.call_tool(db, "request_record_income", {"project_name": "x", "amount": 1})


class TestExecute:
    def _dry(self, db, u, p, amount="100"):
        return writes.dry_run(db, u, "record_income", {"project_name": p.name, "amount": amount})

    def test_confirm_executes_once_with_double_audit(self, db, writes_on):
        u, p = _user(db), _project(db)
        r = self._dry(db, u, p)
        tid = r["card"]["token_id"]
        db.commit()
        before = len(db.query(CapitalTransaction).all())
        ok1 = writes.execute(db, u, tid)
        db.commit()
        assert ok1["ok"], ok1
        assert len(db.query(CapitalTransaction).all()) == before + 1
        actions = {a.action for a in db.query(AuditLog).filter(AuditLog.user_id == u.id).all()}
        assert "ASSISTANT_WRITE" in actions and "CAPITAL_TXN" in actions
        # 幂等：二次确认 → 409，不再新增
        dup = writes.execute(db, u, tid)
        assert dup["status"] == 409
        assert len(db.query(CapitalTransaction).all()) == before + 1

    def test_expired_token_410(self, db, writes_on):
        u, p = _user(db), _project(db)
        r = self._dry(db, u, p)
        tok = db.get(AssistantConfirmToken, uuid.UUID(r["card"]["token_id"]))
        tok.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        db.flush()
        db.commit()
        assert writes.execute(db, u, r["card"]["token_id"])["status"] == 410

    def test_other_users_token_403(self, db, writes_on):
        u, p = _user(db), _project(db)
        r = self._dry(db, u, p)
        db.commit()
        other = _user(db)
        assert writes.execute(db, other, r["card"]["token_id"])["status"] == 403

    def test_cancel_is_terminal(self, db, writes_on):
        u, p = _user(db), _project(db)
        r = self._dry(db, u, p)
        db.commit()
        before = len(db.query(CapitalTransaction).all())
        assert writes.cancel(db, u, r["card"]["token_id"])["ok"]
        assert writes.execute(db, u, r["card"]["token_id"])["status"] == 409
        assert len(db.query(CapitalTransaction).all()) == before

    def test_daily_limit(self, db, writes_on, monkeypatch):
        monkeypatch.setattr(writes.settings, "assistant_write_daily_limit", 1)
        u = _user(db)
        # 造一条今日已用记录
        db.add(AssistantConfirmToken(
            user_id=u.id, action="record_income", params_json={}, idempotency_key=uuid.uuid4().hex,
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
            used_at=dt.datetime.now(dt.timezone.utc)))
        db.flush()
        p = _project(db)
        r = self._dry(db, u, p)
        db.commit()
        assert writes.execute(db, u, r["card"]["token_id"])["status"] == 429