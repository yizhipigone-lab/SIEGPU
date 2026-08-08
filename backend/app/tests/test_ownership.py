"""W7-8 纯函数测试：权属派生 derive_ownership（spec §2.4）。"""
from app.utils.ownership import derive_ownership


def test_derive_self_owned():
    assert derive_ownership("自有") == "表内自有"


def test_derive_direct_lease():
    assert derive_ownership("直租") == "金租表外"


def test_derive_leaseback_is_on_balance():
    """售后回租 → 表内自有（spec §2.4 自有阶段先转固，非表外）。回租出售时才切已处置。"""
    assert derive_ownership("售后回租") == "表内自有"


def test_derive_none_returns_none():
    assert derive_ownership(None) is None


def test_derive_unknown_returns_none():
    """未知 leasing_mode → None（不强行赋值，由导入/显式入参把关）。"""
    assert derive_ownership("foo") is None
