"""应用内消息提醒（F1）服务测试。

覆盖：
- scan_and_persist 扇出到全部活跃用户 + 当天幂等去重（同一 user×kind×ref_id 当天不重复写）
- 跨天重发：昨天写过的同 kind+ref_id，今天再扫会再发一条（永久去重会让用户忽略一次后永不再提醒→资产流失）
- 非活跃用户不收提醒
- list_for_user 未读在前 + unread_count
- mark_read 仅命中本人通知（用户隔离 / 权限只看自己）
- mark_all_read 批量已读
- 用户之间互不干扰（A 全部已读不影响 B 未读数）

alert_service.compute_alerts 本身是 W5-6 已测的存量逻辑，这里 monkeypatch 固定
返回，专门验 notification_service 的扇出/去重/隔离。
"""
import uuid

from app.models.user import User
from app.services import notification_service as svc


def _user(db, username, role="FINANCE_STAFF", active=True):
    u = User(username=username, display_name=username, password_hash="x", role=role, active=active)
    db.add(u); db.flush(); return u


def _fake_alerts():
    """模拟 alert_service 输出：一条带 ref_id（单据级）、一条无 ref_id（池级）。"""
    return [
        {"code": "REPAYMENT_OVERDUE", "level": "高危", "message": "第1期还款逾期", "ref_id": "r-1"},
        {"code": "POOL_INSUFFICIENT", "level": "高危", "message": "资金池不足", "ref_id": None},
    ]


def test_scan_fans_out_to_all_active_users_and_dedups(db, monkeypatch):
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: _fake_alerts())
    _user(db, "notif_a"); _user(db, "notif_b")

    # 2 条告警 × 2 个活跃用户 = 4
    assert svc.scan_and_persist(db) == 4
    # 再扫一次：同 user×kind×ref_id 已存在 → 幂等，0 新增
    assert svc.scan_and_persist(db) == 0


def test_dedup_with_new_ref_id_creates_new_row(db, monkeypatch):
    """同 kind 但不同 ref_id（不同单据）应各写一条，不误去重。"""
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: [
        {"code": "REPAYMENT_OVERDUE", "level": "高危", "message": "第1期", "ref_id": "r-1"},
    ])
    u = _user(db, "notif_dup")
    svc.scan_and_persist(db)  # 写 r-1
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: [
        {"code": "REPAYMENT_OVERDUE", "level": "高危", "message": "第2期", "ref_id": "r-2"},
    ])
    assert svc.scan_and_persist(db) == 1  # 新单据 r-2 → 写一条，r-1 不重复


def test_dedup_is_daily_not_permanent(db, monkeypatch):
    """当天只一条、每日重发：昨天写过的同 kind+ref_id，今天再扫应再写一条。

    防「永久去重」陷阱——用户忽略一次后再也不提醒，到期/逾期资产流失。
    """
    from datetime import datetime, timedelta, timezone
    from app.models.notification import Notification
    _SH = timezone(timedelta(hours=8))

    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: [
        {"code": "REPAYMENT_OVERDUE", "level": "高危", "message": "第1期逾期", "ref_id": "r-1"},
    ])
    u = _user(db, "notif_daily")
    assert svc.scan_and_persist(db) == 1  # 今天写一条

    # 把已写通知倒拨到「昨天」（上海自然日 00:00 之前），模拟跨天
    yesterday = datetime.now(_SH).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    db.query(Notification).filter(Notification.user_id == u.id).update(
        {"created_at": yesterday.astimezone(timezone.utc)}
    )
    db.flush()

    # 次日再扫：底层条件仍在 → 应再发一条（永久去重的话这里会返回 0）
    assert svc.scan_and_persist(db) == 1
    assert len(svc.list_for_user(db, u.id)["items"]) == 2


def test_inactive_users_excluded(db, monkeypatch):
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: _fake_alerts())
    active = _user(db, "notif_active")
    _user(db, "notif_inactive", active=False)
    svc.scan_and_persist(db)
    assert len(svc.list_for_user(db, active.id)["items"]) == 2
    # 非活跃用户一条都没有
    inactive = db.query(User).filter(User.username == "notif_inactive").one()
    assert svc.list_for_user(db, inactive.id)["items"] == []


def test_list_unread_first_and_count(db, monkeypatch):
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: _fake_alerts())
    u = _user(db, "notif_list")
    svc.scan_and_persist(db)
    res = svc.list_for_user(db, u.id)
    assert res["unread_count"] == 2
    assert len(res["items"]) == 2
    # 标一条已读后，未读在前：已读那条排到末尾
    first_id = uuid.UUID(res["items"][0]["id"])
    svc.mark_read(db, u.id, first_id)
    res2 = svc.list_for_user(db, u.id)
    assert res2["unread_count"] == 1
    assert res2["items"][-1]["id"] == str(first_id)  # 已读沉底
    assert res2["items"][-1]["read_at"] is not None


def test_mark_read_only_own(db, monkeypatch):
    """权限只看自己：B 拿 A 的通知 id 标已读 → 不命中。"""
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: _fake_alerts())
    a = _user(db, "notif_mr_a"); b = _user(db, "notif_mr_b")
    svc.scan_and_persist(db)
    a_notif = svc.list_for_user(db, a.id)["items"][0]
    a_id = uuid.UUID(a_notif["id"])

    # B 试图标记 A 的通知 → 不命中
    assert svc.mark_read(db, b.id, a_id) is False
    # A 的通知仍是未读
    assert svc.list_for_user(db, a.id)["unread_count"] == 2
    # A 标自己的 → 命中
    assert svc.mark_read(db, a.id, a_id) is True
    # 重复标同一条（已读）→ 不命中
    assert svc.mark_read(db, a.id, a_id) is False


def test_mark_all_read(db, monkeypatch):
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: _fake_alerts())
    u = _user(db, "notif_mall")
    svc.scan_and_persist(db)
    assert svc.mark_all_read(db, u.id) == 2
    assert svc.list_for_user(db, u.id)["unread_count"] == 0


def test_users_isolated(db, monkeypatch):
    """A 全部已读，不影响 B 的未读数。"""
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: _fake_alerts())
    a = _user(db, "notif_iso_a"); b = _user(db, "notif_iso_b")
    svc.scan_and_persist(db)
    svc.mark_all_read(db, a.id)
    assert svc.list_for_user(db, a.id)["unread_count"] == 0
    assert svc.list_for_user(db, b.id)["unread_count"] == 2


def test_no_alerts_returns_zero(db, monkeypatch):
    monkeypatch.setattr(svc.alert_service, "compute_alerts", lambda d: [])
    _user(db, "notif_empty")
    assert svc.scan_and_persist(db) == 0
