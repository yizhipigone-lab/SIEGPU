from fastapi import Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.models.user import User

from .db import get_db
from .security import create_access_token, decode_token, should_refresh

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


REFRESH_HEADER = "X-Token-Refresh"


def get_current_user(
    response: Response,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    creds = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效凭证")
    try:
        payload = decode_token(token)
    except ValueError:
        raise creds
    user = db.get(User, payload.get("sub"))
    if not user or not user.active or user.deleted_at is not None:
        raise creds
    # 滑动续期：令牌剩余有效期过半消耗时，随响应头下发新令牌，前端拦截器自动替换
    if should_refresh(payload):
        response.headers[REFRESH_HEADER] = create_access_token(
            sub=payload["sub"], role=payload["role"]
        )
    return user


def require_role(*roles: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return _dep
