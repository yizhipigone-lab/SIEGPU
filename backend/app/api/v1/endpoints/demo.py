"""一键载入演示数据（商机5090 全链路）—— 供新手从首页按钮触发。

等价于 `docker compose exec backend python -m app.demo`，但走 HTTP、带权限守卫，
新手不用敲 docker 命令就能看到全流程亮起来。
幂等：DEMO-5090 已存在则返回 loaded=False，不重复造数。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.models.project import Project
from app.models.user import User

router = APIRouter(prefix="/api/demo", tags=["demo"])

DEMO_CODE = "DEMO-5090"


@router.post("/load")
def load_demo(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("ADMIN", "FINANCE_DIRECTOR")),
) -> dict:
    exists = db.execute(
        select(Project).where(Project.code == DEMO_CODE)
    ).scalar_one_or_none()
    if exists:
        return {"loaded": False, "message": "演示项目「商机5090」已存在，无需重复载入"}

    # demo.run() 自管 SessionLocal 与事务（幂等），结束后本请求 session 无需再读写。
    from app.demo import run as _run_demo
    _run_demo()
    return {"loaded": True, "message": "演示项目「商机5090」已载入（18 步全链路）"}
