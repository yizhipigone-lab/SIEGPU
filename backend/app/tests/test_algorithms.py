"""算法纯函数单测（不依赖 DB / FastAPI）。覆盖设计书 §5 的关键公式与审计/复审点。"""
from datetime import date
from decimal import Decimal

from app.utils.billing import billing_amount, first_month_amount, split_tax
from app.utils.capital import allocatable, net_position, pool_balance
from app.utils.depreciation import depreciation_inputs, monthly_schedule
from app.utils.reconcile import is_over_contract, reconcile_contract
from app.utils.repayment_plan import add_months, generate_plan

D = Decimal


# ---------------- 计费 ----------------

def test_first_month_proration_matches_audit_example():
    # 复审 NW2 验算：月租 10 万含税，点亮 2026-09-15，9 月 30 天，剩余 16 天
    amt = first_month_amount(D("100000"), date(2026, 9, 15))
    assert amt == D("53333.33")


def test_billing_period1_vs_full_month():
    assert billing_amount(D("100000"), 1, date(2026, 9, 15)) == D("53333.33")
    assert billing_amount(D("100000"), 2, date(2026, 9, 15)) == D("100000.00")


def test_split_tax_consistency():
    ex, tax = split_tax(D("53333.33"), D("0.13"))
    # 53333.33/1.13 = 47197.637... → 47197.64；税额吸收尾差 6135.69；ex+tax 闭合（单测校验，非手算）
    assert ex == D("47197.64")
    assert tax == D("6135.69")
    assert (ex + tax) == D("53333.33")  # 价税分离闭合


def test_light_on_last_day():
    # 点亮日=月末：只算 1 天
    amt = first_month_amount(D("100000"), date(2026, 2, 28))  # 2026 非闰年，28 天
    assert amt == D("3571.43")  # 100000 * 1 / 28


# ---------------- 折旧 ----------------

def test_depreciation_inputs():
    r = depreciation_inputs(D("1000000"))
    assert r["residual_value"] == D("100000.00")
    assert r["depreciable_value"] == D("900000.00")
    assert r["annual_depreciation"] == D("180000.00")
    assert r["monthly_depreciation"] == D("15000.00")


def test_monthly_schedule_sums_to_depreciable_exact():
    depreciable = D("900000.00")
    sched = monthly_schedule(depreciable, months=60)
    assert len(sched) == 60
    assert sum(sched) == depreciable  # 尾差进末月，精确闭合


def test_monthly_schedule_handles_non_exact_division():
    # 888888.88 / 60 不整除，末期吸收尾差后总和仍精确
    depreciable = D("888888.88")
    sched = monthly_schedule(depreciable, months=60)
    assert sum(sched) == depreciable


# ---------------- 还款计划 ----------------

def test_plan_principal_sum_equals_loan_equal_payment():
    rows = generate_plan(
        principal=D("1000000"),
        annual_rate=D("0.0435"),
        term_periods=4,
        payment_freq="季",
        method="等额本息",
        disbursement_date=date(2026, 8, 10),
    )
    assert len(rows) == 4
    assert [r.period for r in rows] == [1, 2, 3, 4]
    # Σ 计划本金 == 放款额（末期吸收尾差）
    assert sum(r.planned_principal for r in rows) == D("1000000.00")
    # 等额本息：每期总还款额应相同（末期因尾差可能差 0.01，放宽比较）
    totals = [r.planned_total for r in rows]
    assert max(totals) - min(totals) <= D("0.02")


def test_plan_principal_sum_equal_principal():
    rows = generate_plan(
        principal=D("1000000"),
        annual_rate=D("0.0435"),
        term_periods=4,
        payment_freq="季",
        method="等额本金",
        disbursement_date=date(2026, 8, 10),
    )
    assert sum(r.planned_principal for r in rows) == D("1000000.00")
    # 等额本金：利息逐期递减
    interests = [r.planned_interest for r in rows]
    assert interests == sorted(interests, reverse=True)


def test_plan_due_dates_quarterly():
    rows = generate_plan(
        principal=D("1000000"),
        annual_rate=D("0.0435"),
        term_periods=4,
        payment_freq="季",
        method="等额本金",
        disbursement_date=date(2026, 8, 10),
    )
    assert rows[0].due_date == date(2026, 11, 10)
    assert rows[3].due_date == date(2027, 8, 10)


def test_zero_interest_equal_payment():
    rows = generate_plan(
        principal=D("1200000"),
        annual_rate=D("0"),
        term_periods=12,
        payment_freq="月",
        method="等额本息",
        disbursement_date=date(2026, 1, 1),
    )
    assert sum(r.planned_principal for r in rows) == D("1200000.00")
    assert all(r.planned_interest == D("0.00") for r in rows)


def test_add_months_clamps_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)


# ---------------- 资金池 / 可调余额（NF5） ----------------

def test_allocatable_after_partial_allocation():
    # 复审 NF5 修正：注入 500 万，调出 300 万后，可调余额应为 200 万（不被锁成 0）
    ins = [D("5000000")]
    outs = [D("3000000")]
    assert net_position(ins, outs) == D("2000000.00")
    assert allocatable(ins, outs) == D("2000000.00")


def test_allocatable_clamped_to_zero():
    assert allocatable([D("1000000")], [D("3000000")]) == D("0.00")


def test_pool_balance_with_reversal_cancels():
    # 红冲反向记录：方向相反、金额相等，参与求和自动抵消（NF3）
    # 原 IN 100 + 反向 OUT 100 = 0
    assert pool_balance([D("100")], [D("100")]) == D("0.00")


# ---------------- 对账 / 超开 ----------------

def test_reconcile_gaps():
    r = reconcile_contract(
        contract_amount_ex_tax=D("1000000"),
        billed_ex_tax=D("800000"),
        invoiced_ex_tax=D("800000"),
        received_amount=D("500000"),
    )
    assert r["gap_contract_vs_billed"] == D("200000.00")
    assert r["gap_billed_vs_invoiced"] == D("0.00")
    assert r["gap_invoiced_vs_received"] == D("300000.00")


def test_over_contract_detection():
    # 合同 100 万，tolerance 0.1%；已开 90 万 + 新增 11 万 = 101 万 > 100.1 万 → 超开
    assert is_over_contract(
        existing_ex_tax_sum=D("900000"),
        new_ex_tax=D("110000"),
        contract_amount_ex_tax=D("1000000"),
    ) is True
    # 已开 90 万 + 新增 10 万 = 100 万 ≤ 100.1 万 → 不超
    assert is_over_contract(
        existing_ex_tax_sum=D("900000"),
        new_ex_tax=D("100000"),
        contract_amount_ex_tax=D("1000000"),
    ) is False
