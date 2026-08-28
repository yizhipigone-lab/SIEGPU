"""共享常量端点（架构 #5 薄版）：前端启动拉一次，失败回退本地兜底。"""
from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User
from app.services import meta_service

router = APIRouter()


@router.get("/constants")
def get_constants(user: User = Depends(get_current_user)):
    """前后端共享常量：DEVICE_STAGES / POOL_LABELS / STEP_HINTS。"""
    return meta_service.get_constants()
