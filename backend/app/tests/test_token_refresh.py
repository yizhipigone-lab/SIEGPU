"""滑动续期：should_refresh 判断逻辑（纯函数，无需 DB）。

语义：剩余有效期 >= 总时长一半 → 不续；不足一半 → 续。
默认配置 1440 分钟（24h），阈值即 12h。
"""
from app.core.config import settings
from app.core.security import create_access_token, decode_token, should_refresh


def test_fresh_token_not_refreshed():
    payload = decode_token(create_access_token(sub="u1", role="admin"))
    assert not should_refresh(payload)


def test_near_expiry_token_refreshed():
    half = int(settings.access_token_expire_minutes / 2)
    payload = decode_token(
        create_access_token(sub="u1", role="admin", expires_minutes=half - 1)
    )
    assert should_refresh(payload)


def test_missing_exp_not_refreshed():
    assert not should_refresh({"sub": "u1", "role": "admin"})