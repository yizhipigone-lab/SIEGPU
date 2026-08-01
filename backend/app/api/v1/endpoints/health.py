from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

router = APIRouter()


@router.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    # W7：DB 失败时返 503（不回 str(e) 防泄漏），供 compose healthcheck 探活
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"db": "down"})
    return {"status": "ok", "db": "up"}
