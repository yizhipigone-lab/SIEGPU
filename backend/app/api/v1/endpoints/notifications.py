"""应用内消息提醒端点（F1）：铃铛拉列表 / 标已读 / 全部已读。仅本人可见自己的。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import notification_service as svc

router = APIRouter()


@router.get("")
def list_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """当前用户的提醒（未读在前）+ 未读数。前端铃铛轮询。"""
    return svc.list_for_user(db, user.id)


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """全部标已读。"""
    n = svc.mark_all_read(db, user.id)
    db.commit()
    return {"marked": n}


@router.post("/{notif_id}/read")
def read_one(notif_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """单条标已读（仅本人的；别人的 id 静默不命中）。"""
    ok = svc.mark_read(db, user.id, notif_id)
    db.commit()
    return {"read": ok}
