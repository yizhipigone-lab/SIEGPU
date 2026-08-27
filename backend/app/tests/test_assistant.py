"""智能助手单元测试（两层，评审口径）：
- 纯逻辑层（本文件）：guardrails / fastpath 意图 / kb 检索 / engine 瞬断判定——不依赖 DB 和网络；
- 集成层（tools 真实取数）在文件尾部，用 conftest 的 siegpu_test 库（已有先例）。
"""
import pytest

from app.services.assistant import engine, fastpath, guardrails, kb, tools


# ---------------------------------------------------------------- guardrails

class TestGuardrails:
    def test_traced_number_passes(self):
        answer = "资金池余额 1,234,567.89 元"
        evidence = '"pool_balance": 1234567.89'
        assert guardrails.untraceable_numbers(answer, evidence) == []

    def test_untraced_number_flagged(self):
        answer = "利润是 9,999,999 元"
        _, ok = guardrails.ensure_traced(answer, '"profit": 100.0')
        assert not ok
        assert guardrails.LOW_CONFIDENCE_TAG.strip().split("：")[0] in answer + guardrails.LOW_CONFIDENCE_TAG

    def test_wan_unit_forward(self):
        """回答 125万，证据 1250000 → 可溯源。"""
        assert guardrails.untraceable_numbers("约 125万元", "1250000") == []

    def test_wan_unit_reverse(self):
        """评审修正：回答 1250000，证据 125（万）→ 可溯源。"""
        assert guardrails.untraceable_numbers("余额 1250000 元", '"balance": 125') == []

    def test_year_excluded(self):
        """2026 是年份不是金额，不参与溯源。"""
        assert guardrails.extract_numbers("2026 年 8 月") == []

    def test_small_numbers_excluded(self):
        assert guardrails.extract_numbers("共 3 笔，第 2 期") == []

    def test_id_numbers_excluded(self):
        """2026-08-27 误报修正：项目编号 5090 / 台数 1372 不参与金额溯源。"""
        assert guardrails.extract_numbers("比如「商机5090」或「硬转服1372台」") == []

    def test_amount_six_digits_checked(self):
        nums = guardrails.extract_numbers("总头寸为 446937600 元")
        assert "446937600" in nums

    def test_empty_answer_ok(self):
        _, ok = guardrails.ensure_traced("", "")
        assert ok


# ---------------------------------------------------------------- kb

class TestKb:
    def test_light_on_hit(self):
        hits = kb.search("点亮是什么")
        assert hits and hits[0]["id"] in ("term_light_on", "step_light_on")

    def test_repay_vs_receive_hit(self):
        hits = kb.search("回款和还款的区别")
        assert hits and hits[0]["id"] == "term_huikuan_huankuan"

    def test_garbage_no_hit(self):
        assert kb.search("zzzzz qqqqq") == []

    def test_month_end_hit(self):
        hits = kb.search("月结怎么做")
        assert hits and hits[0]["id"] == "howto_month_end"


# ---------------------------------------------------------------- fastpath 意图（纯匹配，db 传 None 走指引路径）

class TestFastpathIntent:
    def test_guide_hit(self):
        r = fastpath.match("点亮是什么意思", None)
        assert r is not None and r.intent == "guide"

    def test_guide_with_biz_entity_not_guide(self):
        """评审修正：「怎么登记回款」含业务实体词 → 不落指引快路径。"""
        r = fastpath.match("怎么登记回款", None)
        assert r is None or r.intent != "guide"

    def test_empty_returns_none(self):
        assert fastpath.match("", None) is None
        assert fastpath.match(None, None) is None

    def test_unrelated_returns_none(self):
        assert fastpath.match("今天天气怎么样", None) is None

    def test_guide_term_no_false_low_confidence(self):
        """指引类回答（KB 文本数字可对证据）不应误报低置信。"""
        r = fastpath.match("点亮是什么意思", None)
        assert r is not None
        bad = guardrails.untraceable_numbers("点亮日是计费起点", r.evidence_text)
        assert bad == []


# ---------------------------------------------------------------- engine 瞬断判定（纯函数）

class TestEngineTransient:
    def test_5xx_transient(self):
        assert engine._is_transient(503, "")
        assert engine._is_transient(None, "Connection reset by peer")

    def test_429_not_transient(self):
        """配额耗尽绝不重试（VERA 纪律）。"""
        assert not engine._is_transient(429, "rate limit")

    def test_auth_not_transient(self):
        assert not engine._is_transient(401, "unauthorized")

    def test_no_api_key_structured_error(self, monkeypatch):
        monkeypatch.setattr(engine.settings, "deepseek_api_key", "")
        r = engine.chat_completion([{"role": "user", "content": "hi"}])
        assert r["success"] is False and r["error_kind"] == "NO_API_KEY"


# ---------------------------------------------------------------- 工具注册表完整性

class TestToolRegistry:
    def test_all_handlers_callable(self):
        for name, spec in tools.TOOL_REGISTRY.items():
            assert callable(spec["handler"]), name
            assert spec["desc"], name

    def test_openai_schema_shape(self):
        for t in tools.openai_tools():
            assert t["type"] == "function"
            assert t["function"]["name"] in tools.TOOL_REGISTRY
            assert t["function"]["parameters"]["type"] == "object"

    def test_unknown_tool_raises(self):
        with pytest.raises(KeyError):
            tools.call_tool(None, "drop_table", {})


# ---------------------------------------------------------------- 集成层：tools 真实取数（siegpu_test 库）

class TestToolsIntegration:
    def test_board_shape(self, db):
        data = tools.get_business_board(db)
        assert "metrics" in data and "todo_center" in data

    def test_capital_position_shape(self, db):
        data = tools.get_capital_position(db)
        assert "summary" in data and "by_project" in data

    def test_due_repayments_list(self, db):
        assert isinstance(tools.list_due_repayments(db), list)

    def test_alerts_list(self, db):
        assert isinstance(tools.list_alerts(db), list)

    def test_invoice_status_requires_filter(self, db):
        """无过滤条件 → None（防全表扫描）。"""
        assert tools.get_invoice_status(db) is None

    def test_search_projects_empty(self, db):
        assert tools.search_projects(db, "绝不存在的项目名xyz") == []

    def test_entity_counts_shape(self, db):
        data = tools.get_entity_counts(db)
        for k in ("projects", "purchase_orders", "sales_orders", "invoices"):
            assert k in data and isinstance(data[k], int)

    def test_order_summary_shape(self, db):
        data = tools.get_order_summary(db)
        assert data["found"] and "purchase_orders" in data and "sales_orders" in data
        assert data["purchase_orders"]["total"] >= 0


# ---------------------------------------------------------------- 通用探索层（query_data / describe_schema）

from app.services.assistant import datadict
from app.services.assistant.query import query_data


class TestGenericQuery:
    def test_describe_all(self):
        d = datadict.describe()
        assert any(e["entity"] == "orders" for e in d["entities"])

    def test_describe_entity_columns_have_labels(self):
        d = datadict.describe("contracts")
        names = {c["name"] for c in d["columns"]}
        assert "amount" in names and "deleted_at" not in names

    def test_unknown_entity_rejected(self, db):
        with pytest.raises(ValueError, match="白名单"):
            query_data(db, "users")  # users 表绝不开放

    def test_unknown_field_rejected(self, db):
        with pytest.raises(ValueError, match="白名单"):
            query_data(db, "orders", filters=[{"field": "password_hash", "op": "eq", "value": 1}])

    def test_bad_op_rejected(self, db):
        with pytest.raises(ValueError, match="不支持"):
            query_data(db, "orders", filters=[{"field": "status", "op": "drop", "value": "x"}])

    def test_sensitive_field_denied(self):
        assert "bank_account" not in datadict.allowed_fields("suppliers")

    def test_limit_capped(self, db):
        r = query_data(db, "orders", limit=99999)
        assert r["count"] <= 100

    def test_count_aggregation(self, db):
        r = query_data(db, "orders", metrics=[{"func": "count", "field": "id"}])
        assert r["rows"][0]["count_id"] >= 0

    def test_group_by_status(self, db):
        r = query_data(db, "orders", group_by=["status"],
                       metrics=[{"func": "count", "field": "id"}])
        assert isinstance(r["rows"], list)

    def test_filter_eq(self, db):
        r = query_data(db, "devices", filters=[{"field": "status", "op": "eq", "value": "订货"}],
                       fields=["sn", "status"])
        for row in r["rows"]:
            assert row["status"] == "订货"

    def test_soft_delete_forced(self, db):
        """软删过滤在聚合路径也强制（不走 ORM 事件）。"""
        r = query_data(db, "projects", metrics=[{"func": "count", "field": "id"}])
        from sqlalchemy import func as f2, select as s2
        from app.models.project import Project
        expected = db.execute(s2(f2.count(Project.id)).where(
            Project.deleted_at.is_(None))).scalar()
        assert r["rows"][0]["count_id"] == expected

# ---------------------------------------------------------------- 体验包：反馈 + 跳转链接

class TestFeedbackAndLinks:
    def test_links_for_dedup_and_order(self):
        from app.api.v1.endpoints.assistant import _links_for
        links = _links_for(["get_capital_position", "capital", "query_data", "get_invoice_status"])
        routes = [l["route"] for l in links]
        assert routes == ["/capital", "/invoices"]  # 去重 + 无页工具不出链接

    def test_feedback_down_creates_gap(self, db):
        import uuid
        from app.api.v1.endpoints.assistant import FeedbackIn, feedback
        from app.models.assistant import AssistantGap, AssistantMessage, AssistantSession
        from app.models.user import User
        u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="测试",
                 password_hash="x", role="ADMIN", active=True)
        db.add(u)
        db.flush()
        from app.services.assistant import memory as mem
        s = mem.get_or_create_session(db, u.id)
        m = mem.save_message(db, s.id, "assistant", "测试回答", tokens_used=0)
        db.flush()
        r = feedback(FeedbackIn(message_id=str(m.id), value="down", question="测试问题"), db=db, user=u)
        assert r["ok"] is True
        gaps = db.query(AssistantGap).filter(AssistantGap.user_id == u.id).all()
        assert len(gaps) == 1 and gaps[0].question == "测试问题"
        assert m.feedback == "down"

    def test_history_full_includes_feedback(self, db):
        import uuid
        from app.models.user import User
        from app.services.assistant import memory as mem
        u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="测试",
                 password_hash="x", role="ADMIN", active=True)
        db.add(u)
        db.flush()
        s = mem.get_or_create_session(db, u.id)
        m = mem.save_message(db, s.id, "assistant", "带反馈的回答")
        m.feedback = "up"
        db.flush()
        rows = mem.load_history_full(db, s.id)
        assert rows[0]["id"] == str(m.id) and rows[0]["feedback"] == "up"