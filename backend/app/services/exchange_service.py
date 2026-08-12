"""汇率与汇兑损益服务（二期 W5-6）。

量纲铁律（docs/superpowers/specs/2026-08-12-w5-6-unit-dimension-table.md）：
- rate DECIMAL(18,8) 全精度存取，永不 round；直接标价法（1 外币 = rate 元人民币）。
- 金额两位；唯一乘除跳「外币 × rate → 人民币」才 q2（ROUND_HALF_UP）。
- amount 的币种由同行 currency_code 决定；NULL=人民币。base_amount 恒人民币，仅外币有值。

汇兑损益（核销钩子，invoice_service.reconcile_invoice 调用）：
- 触发：发票与流水同币种、非本币、invoice_rate 与 settlement_rate 都已填；缺一不动。
- diff = q2(外币额 × (invoice_rate − settlement_rate))；0 不落账。
- ⚠️ 损益流水不填 invoice_id（Invoice.matched_amount=Σ关联流水，填了会污染核销口径）。
service 不 commit 铁律：本模块只 flush，commit 在 endpoint。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.billing import Invoice
from app.models.capital import CapitalTransaction
from app.models.currency import Currency, ExchangeGainLossRule, ExchangeRate
from app.models.project import Contract
from app.utils.reconcile import q2

DEFAULT_BASE = "CNY"


# ------------------------------ 币种 CRUD ------------------------------

def list_currencies(db: Session) -> list[Currency]:
    return list(db.execute(select(Currency).order_by(Currency.is_base.desc(), Currency.code)).scalars().all())


def base_currency_code(db: Session) -> str:
    """本币代码；未配置任何币种时回退 CNY（量纲对照表：currency_code NULL=人民币）。"""
    row = db.execute(select(Currency.code).where(Currency.is_base.is_(True)).limit(1)).first()
    return row[0] if row else DEFAULT_BASE


def create_currency(db: Session, *, code: str, name: str, symbol=None,
                    is_base: bool = False, active: bool = True) -> Currency:
    code = code.strip().upper()
    if not code:
        raise BusinessError("BAD_REQUEST", "币种代码不能为空", 400)
    exists = db.execute(select(Currency.id).where(Currency.code == code)).first()
    if exists is not None:
        raise BusinessError("DUPLICATE", f"币种 {code} 已存在", 409)
    if is_base:  # 本币唯一：新本币上位，旧本币退位
        for c in db.execute(select(Currency).where(Currency.is_base.is_(True))).scalars().all():
            c.is_base = False
    c = Currency(code=code, name=name, symbol=symbol, is_base=is_base, active=active)
    db.add(c)
    db.flush()
    return c


def update_currency(db: Session, cid, data: dict) -> Currency | None:
    c = db.execute(select(Currency).where(Currency.id == cid)).scalar_one_or_none()
    if c is None:
        return None
    if data.get("is_base"):  # 设本币 → 其他退位
        for o in db.execute(select(Currency).where(Currency.is_base.is_(True), Currency.id != c.id)).scalars().all():
            o.is_base = False
    for k, v in data.items():
        if v is not None and k in ("name", "symbol", "is_base", "active"):
            setattr(c, k, v)
    db.flush()
    return c


# ------------------------------ 汇率 ------------------------------

def add_rate(db: Session, *, from_currency: str, to_currency: str, rate: Decimal,
             effective_date: date, rate_type: str = "中间价", source=None) -> ExchangeRate:
    if rate <= 0:
        raise BusinessError("BAD_REQUEST", "汇率必须 > 0", 400)
    r = ExchangeRate(from_currency=from_currency.strip().upper(), to_currency=to_currency.strip().upper(),
                     rate_type=rate_type, rate=rate, effective_date=effective_date, source=source)
    db.add(r)
    db.flush()
    return r


def list_rates(db: Session, from_currency: str | None = None, to_currency: str | None = None,
               limit: int = 200) -> list[ExchangeRate]:
    stmt = select(ExchangeRate).order_by(ExchangeRate.effective_date.desc(),
                                         ExchangeRate.created_at.desc()).limit(limit)
    if from_currency:
        stmt = stmt.where(ExchangeRate.from_currency == from_currency.upper())
    if to_currency:
        stmt = stmt.where(ExchangeRate.to_currency == to_currency.upper())
    return list(db.execute(stmt).scalars().all())


def get_rate(db: Session, from_currency: str, to_currency: str, on_date: date,
             rate_type: str = "中间价") -> Decimal:
    """取汇率：同币 → 1；否则 from/to+rate_type 下 effective_date <= on_date 的最近一条（最近不未来）。
    无记录 → 报错（不静默按 1 折算——静默=假账，D6 对照表 §2）。"""
    f, t = from_currency.strip().upper(), to_currency.strip().upper()
    if f == t:
        return Decimal(1)
    r = db.execute(
        select(ExchangeRate.rate).where(
            ExchangeRate.from_currency == f, ExchangeRate.to_currency == t,
            ExchangeRate.rate_type == rate_type,
            ExchangeRate.effective_date <= on_date,
        ).order_by(ExchangeRate.effective_date.desc()).limit(1)
    ).first()
    if r is None:
        raise BusinessError("NOT_FOUND",
                            f"无汇率记录：{f}→{t}（{rate_type}，{on_date} 或之前）", 404)
    return Decimal(r[0])


def to_base(amount: Decimal, rate: Decimal) -> Decimal:
    """外币 × 率 → 人民币（q2；唯一乘除跳，D6 对照表 §1）。"""
    return q2(amount * rate)


# ------------------------------ 汇兑损益科目规则 CRUD ------------------------------

def list_gl_rules(db: Session) -> list[ExchangeGainLossRule]:
    return list(db.execute(select(ExchangeGainLossRule).order_by(ExchangeGainLossRule.scenario)).scalars().all())


def create_gl_rule(db: Session, *, scenario: str, gl_account_code: str, description=None) -> ExchangeGainLossRule:
    exists = db.execute(select(ExchangeGainLossRule.id).where(
        ExchangeGainLossRule.scenario == scenario)).first()
    if exists is not None:
        raise BusinessError("DUPLICATE", f"场景 {scenario} 的规则已存在", 409)
    r = ExchangeGainLossRule(scenario=scenario, gl_account_code=gl_account_code, description=description)
    db.add(r)
    db.flush()
    return r


# ------------------------------ 汇兑损益（核销钩子） ------------------------------

def compute_exchange_diff(foreign_amount: Decimal, invoice_rate: Decimal,
                          settlement_rate: Decimal) -> Decimal:
    """diff = q2(外币额 × (invoice_rate − settlement_rate))。
    正=损失（收得少/付得多…按方向解释），负=收益，0=无差异。全精度率参与计算，仅最终 q2。"""
    return q2(foreign_amount * (Decimal(invoice_rate) - Decimal(settlement_rate)))


def maybe_book_exchange_diff(db: Session, *, invoice: Invoice, txn: CapitalTransaction,
                             actor_id: uuid.UUID | None = None) -> CapitalTransaction | None:
    """核销钩子：发票↔流水同币种（非本币）且双率齐全 → 落一条汇兑损益流水；否则不动。
    返回损益流水或 None。幂等：idempotency_key=fx:{txn.id}（部分唯一索引兜底）。
    """
    if not invoice.currency_code or not txn.currency_code:
        return None
    if invoice.currency_code != txn.currency_code:
        return None
    if invoice.currency_code == base_currency_code(db):
        return None
    if invoice.invoice_rate is None or txn.settlement_rate is None:
        return None

    diff = compute_exchange_diff(txn.amount, invoice.invoice_rate, txn.settlement_rate)
    if diff == 0:
        return None
    # 幂等守卫：同一结算流水的损益只落一次（fx:{txn.id}；部分唯一索引 uq_ct_idem 兜底）
    existing = db.execute(select(CapitalTransaction.id).where(
        CapitalTransaction.idempotency_key == f"fx:{txn.id}")).first()
    if existing is not None:
        return None
    # 方向：应收（收钱）diff>0=损失 OUT / diff<0=收益 IN；应付（付钱）相反
    if invoice.direction == "RECEIVABLE":
        direction = "OUT" if diff > 0 else "IN"
    else:
        direction = "IN" if diff > 0 else "OUT"
    contract = db.get(Contract, invoice.contract_id)
    gl = db.execute(select(ExchangeGainLossRule).where(
        ExchangeGainLossRule.scenario == ("收款核销" if invoice.direction == "RECEIVABLE" else "付款核销")
    )).scalars().first()
    fx = CapitalTransaction(
        project_id=contract.project_id if contract else None,
        source_type="汇兑损益", direction=direction,
        amount=abs(diff), transaction_date=txn.transaction_date,
        contract_id=invoice.contract_id,
        # ⚠️ 不填 invoice_id：matched_amount=Σ关联流水，填了会把损益计入已核销金额
        category="汇兑损益",
        idempotency_key=f"fx:{txn.id}",
        note=(f"汇兑损益：发票 {invoice.invoice_no or invoice.id} 开票率 {invoice.invoice_rate} "
              f"vs 结算率 {txn.settlement_rate}，外币额 {txn.amount} {invoice.currency_code}"
              + (f"；科目 {gl.gl_account_code}" if gl else "")),
        created_by=actor_id,
    )
    db.add(fx)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="CAPITAL_TXN", target_type="capital_transaction",
               target_id=fx.id,
               after_json={"source_type": "汇兑损益", "direction": direction, "amount": str(abs(diff)),
                           "invoice_id": str(invoice.id), "settlement_txn_id": str(txn.id)})
    return fx
