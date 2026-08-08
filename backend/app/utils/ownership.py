"""权属派生（一期 W7-8 §2.4）：由 leasing_mode 推导上架时的设备权属。

settle_ownership 的纯函数核心——device.ownership 为 None 时，由 leasing_mode 派生：
- 自有     → 表内自有（FA 卡，进 assets）
- 直租     → 金租表外（off_balance_registers）
- 售后回租 → 表内自有（**自有阶段先转固**；回租出售时再切已处置 + 表外）
- None/未知 → None（不强行赋值，由导入/显式入参把关）

决策 D1：settle_ownership 只填 None，显式入参永远优先 → 落点在 _sync_device_asset 上架分支，
不落 create_device（spec 明示"上架时执行"，且 import/显式传参路径不动）。
"""
from typing import Optional

LEASING_MODE_TO_OWNERSHIP = {
    "自有": "表内自有",
    "直租": "金租表外",
    "售后回租": "表内自有",  # spec §2.4：自有阶段先转固（非表外）
}


def derive_ownership(leasing_mode: Optional[str]) -> Optional[str]:
    """由 leasing_mode 派生 ownership。None/未知模式 → None（不派生）。"""
    if leasing_mode is None:
        return None
    return LEASING_MODE_TO_OWNERSHIP.get(leasing_mode)
