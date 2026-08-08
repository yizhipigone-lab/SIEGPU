"""W7-8 纯函数测试：折旧截断 / 账面价值 / 出售损益（M1 审计数学修正）。

M1 核心：truncated_schedule 末期**不吸收**剩余净值（吸收是 monthly_schedule 全 60 期的模式）；
carrying_amount 独立计算 = 原值 - q2(monthly × 已过整月)，与 truncated_schedule 解耦。
"""
from datetime import date
from decimal import Decimal

from app.utils.depreciation import (
    carrying_amount,
    compute_sale_gain_loss,
    depreciation_inputs,
    elapsed_whole_months,
    truncated_schedule,
)


# ---------- truncated_schedule：每期=monthly，不吸收 ----------

def test_truncated_each_period_equals_monthly():
    """截断每期 = monthly_depreciation（q2 对齐），末期不吸收。"""
    dep = depreciation_inputs(Decimal("960000"))
    sched = truncated_schedule(dep["monthly_depreciation"], 12)
    assert len(sched) == 12
    assert all(p == dep["monthly_depreciation"] for p in sched)
    assert sum(sched) == dep["monthly_depreciation"] * 12


def test_truncated_does_not_absorb_remaining_net_value():
    """M1 反例：Σ(truncated_12) 远小于 depreciable_value——不把 60-N 个月剩余折旧塞进末期。"""
    dep = depreciation_inputs(Decimal("960000"))
    sched = truncated_schedule(dep["monthly_depreciation"], 12)
    assert sum(sched) < dep["depreciable_value"]


def test_truncated_zero_elapsed():
    assert truncated_schedule(Decimal("14400"), 0) == []


# ---------- carrying_amount：独立于 truncated_schedule ----------

def test_carrying_amount_n12_is_original_minus_12_monthly():
    """M1 关键：N=12 → carrying ≈ original - 12×monthly（远未折完，不是 residual_value）。"""
    dep = depreciation_inputs(Decimal("960000"))
    c = carrying_amount(Decimal("960000"), dep["monthly_depreciation"], 12)
    expected = (Decimal("960000") - dep["monthly_depreciation"] * 12).quantize(Decimal("0.01"))
    assert c == expected
    assert c > dep["residual_value"]  # 12 月远未折完


def test_carrying_amount_zero_elapsed_is_original():
    """未起折旧（已转固未运营即出售）→ 账面 = 原值。"""
    dep = depreciation_inputs(Decimal("960000"))
    assert carrying_amount(Decimal("960000"), dep["monthly_depreciation"], 0) == Decimal("960000.00")


def test_carrying_amount_floored_at_residual_when_fully_depreciated():
    """全折旧（60 期）后账面 = 残值（floor）。"""
    dep = depreciation_inputs(Decimal("960000"))
    c = carrying_amount(Decimal("960000"), dep["monthly_depreciation"], 60,
                        residual_value=dep["residual_value"])
    assert c == dep["residual_value"]


def test_carrying_amount_over_depreciated_clamps_to_residual():
    """超期（70 月）累计 > 原值-残值 → floor 到残值，不出现负账面。"""
    dep = depreciation_inputs(Decimal("960000"))
    c = carrying_amount(Decimal("960000"), dep["monthly_depreciation"], 70,
                        residual_value=dep["residual_value"])
    assert c == dep["residual_value"]


# ---------- compute_sale_gain_loss ----------

def test_sale_gain_loss_gain_loss_flat():
    assert compute_sale_gain_loss(Decimal("100"), Decimal("80")) == Decimal("20.00")
    assert compute_sale_gain_loss(Decimal("50"), Decimal("80")) == Decimal("-30.00")
    assert compute_sale_gain_loss(Decimal("80"), Decimal("80")) == Decimal("0.00")


# ---------- elapsed_whole_months ----------

def test_elapsed_whole_months_bounds():
    assert elapsed_whole_months(date(2026, 1, 15), date(2026, 3, 20)) == 2
    assert elapsed_whole_months(date(2026, 1, 15), date(2026, 3, 10)) == 1  # 3 月未满整月
    assert elapsed_whole_months(date(2026, 1, 15), date(2026, 1, 20)) == 0  # 同月未满
    assert elapsed_whole_months(date(2026, 1, 15), date(2027, 1, 20)) == 12
    assert elapsed_whole_months(date(2026, 1, 15), date(2026, 1, 10)) == 0  # end < start
