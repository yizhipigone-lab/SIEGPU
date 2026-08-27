"""#4 架构深化：@audited 声明式审计装饰器。

契约：装饰 service 写函数 → 函数成功返回后自动落一条 audit_logs 行
（action/target_type/target_id/after_json=fields 快照/user_id=actor 参数探取）；
只 add 不 flush（endpoint commit 铁律）；函数抛异常不留审计。
"""
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models.user import AuditLog
from app.services.audit_service import audited


class _FakeEntity:
    """装饰器只读 id 与声明字段——纯 Python 对象即可测。"""

    def __init__(self, **kw):
        self.id = uuid.uuid4()
        for k, v in kw.items():
            setattr(self, k, v)


def _last_audit(db) -> AuditLog | None:
    return db.execute(select(AuditLog).order_by(AuditLog.at.desc())).scalars().first()


def test_decorator_logs_returned_entity(db):
    @audited(action="CAPITAL_TXN", target_type="capital_transaction",
             fields=["source_type", "direction", "amount"])
    def _write(db, *, created_by, source_type, direction, amount):
        return _FakeEntity(source_type=source_type, direction=direction,
                           amount=Decimal("500"))

    ent = _write(db, created_by=None, source_type="自有资金", direction="IN",
                 amount=Decimal("500"))
    row = _last_audit(db)
    assert row is not None
    assert row.action == "CAPITAL_TXN"
    assert row.entity_type == "capital_transaction"
    assert row.entity_id == ent.id
    assert row.after_json == {"source_type": "自有资金", "direction": "IN",
                              "amount": "500"}
    assert row.before_json is None  # 创建场景无 before
    assert row.user_id is None


def test_decorator_probes_actor_param(db):
    from app.models.user import User

    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="t", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u)
    db.flush()

    @audited(action="ALLOCATE", target_type="capital_allocation", fields=["amount"])
    def _write(db, *, approved_by, amount):
        return _FakeEntity(amount=amount)

    ent = _write(db, approved_by=u.id, amount=Decimal("100"))
    assert _last_audit(db).user_id == u.id
    assert _last_audit(db).entity_id == ent.id


def test_decorator_update_arg_snapshots_before_and_after(db):
    """update 场景：update_arg 实体已持久化 → before 快照 + after 对比（用真 ORM 实体验证）。"""
    from app.models.user import User

    u = User(username=f"u{uuid.uuid4().hex[:6]}", display_name="旧名", password_hash="x",
             role="FINANCE_DIRECTOR", active=True)
    db.add(u)
    db.flush()  # 先持久化，装饰器才能识别「已存在」

    @audited(action="UPDATE", target_type="user",
             fields=["display_name", "role"], update_arg="user")
    def _rename(db, *, operator_id, user, new_name):
        user.display_name = new_name
        return user

    _rename(db, operator_id=None, user=u, new_name="新名")
    row = _last_audit(db)
    assert row.before_json == {"display_name": "旧名", "role": "FINANCE_DIRECTOR"}
    assert row.after_json == {"display_name": "新名", "role": "FINANCE_DIRECTOR"}
    assert row.entity_id == u.id


def test_decorator_none_result_logs_nothing(db):
    @audited(action="SKIP", target_type="thing", fields=["x"])
    def _write(db):
        return None

    _write(db)
    assert _last_audit(db) is None or _last_audit(db).action != "SKIP"


def test_decorator_exception_leaves_no_audit(db):
    @audited(action="BOOM", target_type="thing", fields=["x"])
    def _write(db):
        raise ValueError("业务失败")

    try:
        _write(db)
    except ValueError:
        pass
    assert _last_audit(db) is None or _last_audit(db).action != "BOOM"
