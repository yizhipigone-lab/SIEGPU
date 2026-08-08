"""应用内消息提醒服务（F1）。

- scan_and_persist：把 alert_service.compute_alerts 的结果按活跃用户扇出写 notifications，
  当天幂等去重（同一 user×kind×ref_id 「当天」已写过则跳过；次日若底层条件仍在会再发一条，
  防「忽略一次就再也不提醒」导致资产流失）。多次扫描/重启当天不重复。
- list_for_user / mark_read / mark_all_read：支撑前端铃铛。
仅应用内提醒，不接邮件/企微。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User
from . import alert_service

# Asia/Shanghai = UTC+8，无夏令时，用固定偏移避免 tzdata 依赖。
_SH_TZ = timezone(timedelta(hours=8))

# 告警 code → (标题, ref_type 前端跳转分类)
_KIND_META: dict[str, tuple[str, str | None]] = {
    "REPAYMENT_OVERDUE": ("还款逾期", "repayment"),
    "ALLOCATION_OVERDUE": ("调配逾期", "capital"),
    "DISBURSE_MISMATCH": ("金租放款不符", "leasing"),
    "DISBURSE_DELAY": ("金租放款延迟", "leasing"),
    "POOL_INSUFFICIENT": ("资金池不足", "capital"),
    "DELIVERY_STUCK": ("交付停滞", "delivery"),
    "CONTRACT_EXPIRING": ("合同即将到期", "contract"),
    "WORKFLOW_STUCK": ("项目流程停滞", "project"),
}


def _sent_today(db: Session, user_id, kind: str, ref_id: str | None) -> bool:
    """同一 user×kind×ref_id 「当天（Asia/Shanghai 自然日）」是否已写过。

    永久去重会使用户忽略一次后再也不提醒（资产流失风险），故改为当天幂等：
    当天多次扫描只写一条；次日若底层告警条件仍在（compute_alerts 仍产出），会再发一条。
    ref_id 为 None 时查 IS NULL；created_at 存 UTC，与 +8 自然日零点（转 UTC）比较。
    """
    start_of_today = datetime.now(_SH_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    ref_cond = Notification.ref_id.is_(None) if ref_id is None else Notification.ref_id == ref_id
    return db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id, Notification.kind == kind, ref_cond,
            Notification.created_at >= start_of_today,
        )
    ).first() is not None


def scan_and_persist(db: Session) -> int:
    """扫 alert_service → 扇出到全部活跃用户 → 当天幂等写入。返回新增条数。"""
    alerts = alert_service.compute_alerts(db)
    if not alerts:
        return 0
    users = db.execute(select(User).where(User.active.is_(True))).scalars().all()
    created = 0
    for a in alerts:
        kind = a["code"]
        title, ref_type = _KIND_META.get(kind, (kind, None))
        ref_id = a.get("ref_id")
        body = a["message"]
        level = a.get("level", "提示")
        for u in users:
            if _sent_today(db, u.id, kind, ref_id):
                continue
            db.add(Notification(
                user_id=u.id, kind=kind, ref_type=ref_type, ref_id=ref_id,
                title=title, body=body, level=level,
            ))
            created += 1
    return created


def list_for_user(db: Session, user_id, limit: int = 50) -> dict:
    """当前用户：未读在前 + 近期，附未读数。"""
    rows = db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.read_at.is_(None).desc(), Notification.created_at.desc())
        .limit(limit)
    ).scalars().all()
    unread = db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id, Notification.read_at.is_(None),
        )
    ).all()
    return {
        "items": [_to_dict(r) for r in rows],
        "unread_count": len(unread),
    }


def mark_read(db: Session, user_id, notif_id) -> bool:
    """标记单条已读（仅本人的）。返回是否命中。调用方负责 commit。"""
    res = db.execute(
        update(Notification)
        .where(Notification.id == notif_id, Notification.user_id == user_id,
               Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    return res.rowcount > 0


def mark_all_read(db: Session, user_id) -> int:
    """当前用户全部未读标已读。返回更新条数。调用方负责 commit。"""
    res = db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    return res.rowcount


def _to_dict(r: Notification) -> dict:
    return {
        "id": str(r.id),
        "kind": r.kind,
        "ref_type": r.ref_type,
        "ref_id": r.ref_id,
        "title": r.title,
        "body": r.body,
        "level": r.level,
        "read_at": r.read_at.isoformat() if r.read_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
