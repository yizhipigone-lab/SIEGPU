from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from .config import settings


def hash_password(raw: str) -> str:
    # bcrypt 上限 72 字节；超长截断（业务密码远短于此，仅兜底，避开 bcrypt 5.0 抛错）
    pw = raw.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(*, sub: str, role: str, expires_minutes: int | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": sub, "role": role, "exp": exp},
        settings.jwt_secret,
        algorithm=settings.jwt_algo,
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algo])
    except JWTError as e:
        raise ValueError("invalid token") from e


def should_refresh(payload: dict) -> bool:
    """滑动续期：剩余有效期不足总时长一半时，由 get_current_user 在响应头里发新令牌。

    效果：只要持续在用就永不过期；闲置超过 access_token_expire_minutes 才需重新登录。
    """
    exp = payload.get("exp")
    if not exp:
        return False
    remaining = float(exp) - datetime.now(timezone.utc).timestamp()
    return remaining < settings.access_token_expire_minutes * 60 / 2
