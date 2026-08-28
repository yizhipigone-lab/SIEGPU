"""客户对账单（F3）聚合测试。

口径：全部不含税，三流（计费/开票/回款）+ 两个 gap 可直接相减。
刻意覆盖 receivables_aging 的隐性 bug（依赖从未写入的「已收款」状态）——
本对账单用 Invoice.paid_date 判定回款，不依赖 billing 状态。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.models.billing import Billing, Invoice
from app.models.master import Customer
from app.models.project import Project
from app.services import contract_service as csvc
from app.services import report_service as rsvc


def _contract(db, cust_id, amount):
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    return csvc.create_contract(db, project_id=p.id, type="SALES", party_id=cust_id,
                                amount=amount, tax_rate=Decimal("0.13"))


def _billing(db, contract, amount_ex_tax, status="未开"):
    db.add(Billing(
        project_id=contract.project_id, contract_id=contract.id, period_index=1,
        period_label="2026-01", billing_date=date(2026, 1, 31), days_in_period=31,
        amount=amount_ex_tax * Decimal("1.13"), amount_ex_tax=amount_ex_tax,
        tax_amount=amount_ex_tax * Decimal("0.13"), tax_rate=Decimal("0.13"), status=status,
    )); db.flush()


def _invoice(db, contract, amount_ex_tax, paid=False, status="已开"):
    inv = Invoice(
        contract_id=contract.id, direction="RECEIVABLE", amount=amount_ex_tax * Decimal("1.13"),
        amount_ex_tax=amount_ex_tax, tax_amount=amount_ex_tax * Decimal("0.13"),
        tax_rate=Decimal("0.13"), issue_date=date(2026, 2, 1), status=status,
        paid_date=date(2026, 2, 10) if paid else None,
    )
    db.add(inv); db.flush(); return inv


def test_statement_aggregates_across_contracts(db):
    cust = Customer(name="对账客户A"); db.add(cust); db.flush()
    c1 = _contract(db, cust.id, Decimal("1000"))
    c2 = _contract(db, cust.id, Decimal("2000"))
    _billing(db, c1, Decimal("800"))
    _billing(db, c2, Decimal("1500"))
    _invoice(db, c1, Decimal("500"), paid=True)
    _invoice(db, c2, Decimal("1000"), paid=False)

    st = rsvc.customer_statement(db, cust.id)
    assert st["customer_name"] == "对账客户A"
    assert st["contract_amount"] == Decimal("3000.00")
    assert st["billed"] == Decimal("2300.00")        # 800 + 1500
    assert st["invoiced"] == Decimal("1500.00")      # 500 + 1000
    assert st["received"] == Decimal("500.00")       # 仅 c1 已回款（不含税口径）
    assert st["gap_unbilled"] == Decimal("700.00")   # 3000 - 2300
    assert st["gap_uncollected"] == Decimal("1000.00")  # 1500 - 500
    assert len(st["contracts"]) == 2
    assert len(st["line_items"]) == 4                 # 2 计费 + 2 开票/回款


def test_statement_excludes_reversed(db):
    cust = Customer(name="对账客户B"); db.add(cust); db.flush()
    c = _contract(db, cust.id, Decimal("1000"))
    _billing(db, c, Decimal("300"))                       # 有效
    _billing(db, c, Decimal("9999"), status="已红冲")     # 红冲，应剔除
    _invoice(db, c, Decimal("200"), paid=True)            # 有效已回款
    _invoice(db, c, Decimal("9999"), status="已红冲")     # 红冲，应剔除

    st = rsvc.customer_statement(db, cust.id)
    assert st["billed"] == Decimal("300.00")     # 红冲 9999 不计入
    assert st["received"] == Decimal("200.00")   # 红冲 9999 不计入


def test_statement_summary_lists_customers_sorted(db):
    cust_a = Customer(name="客户A-大额未回"); db.add(cust_a); db.flush()
    cust_b = Customer(name="客户B-已结清"); db.add(cust_b); db.flush()
    ca = _contract(db, cust_a.id, Decimal("1000"))
    _billing(db, ca, Decimal("1000"))
    _invoice(db, ca, Decimal("1000"), paid=False)   # 未回款 1000
    cb = _contract(db, cust_b.id, Decimal("500"))
    _billing(db, cb, Decimal("500"))
    _invoice(db, cb, Decimal("500"), paid=True)     # 已回款，未回款 0

    rows = rsvc.customer_statement_summary(db)
    names = [r["customer_name"] for r in rows]
    assert "客户A-大额未回" in names and "客户B-已结清" in names
    # 按 gap_uncollected 倒序：A(1000) 应排在 B(0) 前面
    a = next(r for r in rows if r["customer_name"] == "客户A-大额未回")
    b = next(r for r in rows if r["customer_name"] == "客户B-已结清")
    assert a["gap_uncollected"] == Decimal("1000.00")
    assert b["gap_uncollected"] == Decimal("0.00")
    assert rows.index(a) < rows.index(b)


def test_statement_not_found(db):
    with pytest.raises(BusinessError, match="客户不存在"):
        rsvc.customer_statement(db, uuid.uuid4())


def test_statement_period_filter(db):
    """缺陷#18：对账单支持「当期」口径——只含该月计费/开票/回款（累计口径不变）。"""
    cust = Customer(name="对账客户C"); db.add(cust); db.flush()
    c = _contract(db, cust.id, Decimal("10000"))
    _billing(db, c, Decimal("1000"))                              # period_label 2026-01
    b2 = Billing(
        project_id=c.project_id, contract_id=c.id, period_index=2,
        period_label="2026-02", billing_date=date(2026, 2, 28), days_in_period=28,
        amount=Decimal("1130"), amount_ex_tax=Decimal("1000"),
        tax_amount=Decimal("130"), tax_rate=Decimal("0.13"), status="未开",
    )
    db.add(b2); db.flush()
    _invoice(db, c, Decimal("500"), paid=True)                    # issue 2026-02-01, paid 2026-02-10
    inv2 = Invoice(
        contract_id=c.id, direction="RECEIVABLE", amount=Decimal("565"),
        amount_ex_tax=Decimal("500"), tax_amount=Decimal("65"), tax_rate=Decimal("0.13"),
        issue_date=date(2026, 3, 5), status="已开", paid_date=None,
    )
    db.add(inv2); db.flush()

    # 累计口径（现状）
    st = rsvc.customer_statement(db, cust.id)
    assert st["billed"] == Decimal("2000.00") and st["invoiced"] == Decimal("1000.00")
    # 当期 2026-02：只含 2 月计费 + 2 月开票/回款
    st2 = rsvc.customer_statement(db, cust.id, period="2026-02")
    assert st2["billed"] == Decimal("1000.00")        # 仅 period_label=2026-02
    assert st2["invoiced"] == Decimal("500.00")       # 仅 2 月开票
    assert st2["received"] == Decimal("500.00")       # 仅 2 月回款
    assert st2["gap_uncollected"] == Decimal("0.00")  # 当期 500-500
    # 当期行明细只有 2 条（2月计费 + 2月回款），3月开票被剔除
    assert len(st2["line_items"]) == 2
    assert all(li["date"].startswith("2026-02") for li in st2["line_items"])
