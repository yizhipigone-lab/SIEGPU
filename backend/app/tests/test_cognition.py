"""认知层测试（M-A A-5）：召回/保存红线/衰减归因/越权/预算/自动别名。"""
import uuid

import pytest

from app.models.user import User
from app.services.assistant import memory, tools


def _user(db, role="ADMIN") -> User:
    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="测试", password_hash="x", role=role, active=True)
    db.add(u)
    db.flush()
    return u


class TestSaveCognition:
    def test_user_teach_saves_confidence_100(self, db):
        u = _user(db)
        row, msg = memory.save_cognition(db, u.id, "七号项目", "指项目 商机5090", "entity_alias", source="user")
        assert row and row.confidence == 100

    def test_redline_rejects_amounts(self, db):
        u = _user(db)
        row, msg = memory.save_cognition(db, u.id, "回款额", "上季度回款 12,345,678.90 元", "glossary_pref")
        assert row is None and "金额" in msg

    def test_bad_kind_rejected(self, db):
        u = _user(db)
        row, msg = memory.save_cognition(db, u.id, "k", "v", "hack")
        assert row is None

    def test_reteach_overwrites(self, db):
        u = _user(db)
        memory.save_cognition(db, u.id, "七号", "指A", "entity_alias", source="user")
        row, msg = memory.save_cognition(db, u.id, "七号", "指B", "entity_alias", source="user")
        assert row.value == "指B" and row.confidence == 100


class TestRecall:
    def test_substring_recall(self, db):
        u = _user(db)
        memory.save_cognition(db, u.id, "七号项目", "指项目 商机5090", "entity_alias", source="user")
        hits = memory.relevant_cognition(db, u.id, "七号项目现在什么状态")
        assert hits and hits[0]["key"] == "七号项目"

    def test_user_isolation(self, db):
        a, b = _user(db), _user(db)
        memory.save_cognition(db, a.id, "七号", "指A", "entity_alias", source="user")
        assert memory.relevant_cognition(db, b.id, "七号是什么") == []

    def test_budget_truncation(self, db):
        u = _user(db)
        for i in range(30):
            memory.save_cognition(db, u.id, f"关键词{i:02d}", "x" * 200, "entity_alias", source="user")
        block = memory.format_cognition_block(memory.relevant_cognition(db, u.id, "关键词"))
        assert len(block) <= memory.COGNITION_BUDGET + 120  # 允许头部模板字符

    def test_block_wrapped_in_data(self, db):
        u = _user(db)
        memory.save_cognition(db, u.id, "口径", "报万元", "glossary_pref", source="user")
        block = memory.format_cognition_block(memory.relevant_cognition(db, u.id, "口径"))
        assert "<data" in block and "</data>" in block


class TestDecay:
    def test_downvote_decays_and_soft_deletes(self, db):
        u = _user(db)
        s = memory.get_or_create_session(db, u.id)
        row, _ = memory.save_cognition(db, u.id, "七号", "指A", "entity_alias", source="auto")
        assert row.confidence == 50
        m = memory.save_message(db, s.id, "assistant", "回答",
                                tool_calls={"cognition_used": [str(row.id)]})
        n = memory.decay_cognition_for_message(db, m)
        assert n == 1
        db.refresh(row)
        assert row.confidence == 20
        # 再衰两次 → 软删
        memory.decay_cognition_for_message(db, m)
        memory.decay_cognition_for_message(db, m)
        db.refresh(row)
        assert row.deleted_at is not None

    def test_no_attribution_no_decay(self, db):
        u = _user(db)
        s = memory.get_or_create_session(db, u.id)
        m = memory.save_message(db, s.id, "assistant", "无认知痕迹")
        assert memory.decay_cognition_for_message(db, m) == 0


class TestAutoAlias:
    def test_capture_on_unique_hit(self, db):
        from app.models.project import Project
        u = _user(db)
        proj = Project(name=f"商机测试{uuid.uuid4().hex[:4]}全链路", status="进行中")
        db.add(proj)
        db.flush()
        from app.api.v1.endpoints.assistant import _try_auto_alias
        _try_auto_alias(db, u.id, "商机测试现在怎么样", ["商机测试"])
        hits = memory.relevant_cognition(db, u.id, "商机测试")
        assert hits and hits[0]["value"].endswith(proj.name)

    def test_denied_for_pronouns(self, db):
        u = _user(db)
        from app.api.v1.endpoints.assistant import _try_auto_alias
        _try_auto_alias(db, u.id, "那个项目", ["那个"])
        assert memory.relevant_cognition(db, u.id, "那个") == []


class TestCognitionTools:
    def test_tool_requires_user(self, db):
        """user 未注入 → 结构化报错（不炸）。"""
        r = tools.call_tool(db, "save_cognition", {"key": "k", "value": "v", "kind": "entity_alias"}, user=None)
        assert isinstance(r, dict) and "error" in r

    def test_tool_with_user_saves(self, db):
        u = _user(db)
        r = tools.call_tool(db, "save_cognition",
                            {"key": "口径A", "value": "报万元", "kind": "glossary_pref"}, user=u)
        assert r.get("saved") is True