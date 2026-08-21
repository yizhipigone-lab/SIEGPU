"""付款三重管控 + 多对多核销服务（二期 W11-12，二期最复杂模块）。

链路：申请（可挂预付款冲抵）→ 审批（approvals，approval_service 级联状态）→ 登记（落
capital_transactions，多币种+结算率）→ 核销（payment_settlements 多对多：一笔流水 ↔ 多发票/
多批次/多台设备按金额逐台多行；发票核销满 → 已核销+paid_date；外币核销 → 汇兑损益按设备
价值占比分摊至设备（复用 W5-6 compute_exchange_diff 计算口径 + 保险 allocate_by_value 分摊））。

口径守卫：
- payment_settlements 不写 txn.invoice_id（那是旧 1:1 核销路径）；Invoice.matched_amount
  column_property 已改为「旧链接 + 新核销行」两路合计（互斥不双计）。
- 预付款冲抵 = 视同结转：实付现金 = 申请额 − 冲抵额；冲抵额按设备剩余预付款 FIFO 抵扣
  （写 W9-10 的 devices.prepayment_settled_amount，单源不双账）。
service 不 commit 铁律：只 flush，commit 在 endpoint。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.billing import Invoice
from app.models.capital import CapitalTransaction
from app.models.device import Device
from app.models.payment import Approval, PaymentRequest, PaymentSettlement
from app.models.project import Contract, Project
from app.services import approval_service
from app.services.exchange_service import base_currency_code, compute_exchange_diff, to_base
from app.services.insurance_service import allocate_by_value
from app.utils.reconcile import q2


# ------------------------------ 申请 → 审批 ------------------------------

def _project_prepayment_remaining(db: Session, project_id) -> Decimal:
    """项目设备预付款剩余可冲抵额（D2 单源：Σ(prepayment_amount − settled_amount)，未结清）。"""
    total = Decimal(0)
    for d in db.execute(select(Device).where(
            Device.project_id == project_id, Device.prepayment_amount > 0,
            Device.prepayment_settled.is_(False))).scalars().all():
        total += d.prepayment_amount - (d.prepayment_settled_amount or Decimal(0))
    return total


def create_request(db: Session, *, project_id, amount: Decimal, contract_id=None,
                   direction: str = "OUT", currency_code=None, reason=None,
                   prepayment_offset: Decimal = Decimal("0"),
                   requested_by=None) -> PaymentRequest:
    proj = db.get(Project, project_id)
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    if amount <= 0:
        raise BusinessError("BAD_REQUEST", "金额必须 > 0", 400)
    if prepayment_offset < 0 or prepayment_offset >= amount:
        raise BusinessError("BAD_REQUEST", "预付款冲抵必须 ≥0 且 < 申请金额", 400)
    if prepayment_offset > 0:
        remaining = _project_prepayment_remaining(db, project_id)
        if prepayment_offset > remaining:
            raise BusinessError("BAD_REQUEST",
                                f"预付款冲抵 {prepayment_offset} 超项目剩余可冲抵额 {remaining}", 400)
    pr = PaymentRequest(project_id=project_id, contract_id=contract_id, direction=direction,
                        amount=amount, currency_code=currency_code, reason=reason,
                        prepayment_offset=prepayment_offset, requested_by=requested_by)
    db.add(pr)
    db.flush()
    a = approval_service.submit(db, biz_type="付款申请", biz_id=pr.id,
                                title=f"付款申请 {amount}（项目 {proj.name}）", submitted_by=requested_by)
    pr.approval_id = a.id
    db.flush()
    return pr


# ------------------------------ 登记（审批通过 → 落资金流水） ------------------------------

# 四期 W4：付款资金池 → source_type 映射（金租池支出不再被置换引擎当作待置换桥资）
_POOL_SOURCE = {"BANK": "银行流贷", "OWN": "自有资金", "LEASING": "金租融资"}


def disburse(db: Session, request_id, *, transaction_date: date, settlement_rate=None,
             bank_id=None, actor_id=None, pool_splits=None) -> CapitalTransaction:
    """登记付款：已批准 → 落 capital_transaction（实付现金 = 申请额 − 预付款冲抵额）。
    冲抵额按设备剩余预付款 FIFO 抵扣（视同结转，写 devices.prepayment_settled_amount 单源）。
    四期 W4：pool_splits 给定时按资金池拆分（金租/银行/自有各出多少），逐池生成流水并校验余额。"""
    pr = db.get(PaymentRequest, request_id)
    if not pr or pr.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "付款申请不存在", 404)
    if pr.status == "待审批":
        raise BusinessError("ILLEGAL_TRANSITION", "付款申请未审批通过，不可登记", 409)
    if pr.status != "已批准":
        raise BusinessError("ILLEGAL_TRANSITION", f"付款申请状态 {pr.status} 不可登记", 409)

    cash = pr.amount - pr.prepayment_offset
    base_amount = (to_base(pr.amount, settlement_rate) if pr.currency_code and settlement_rate else None)
    note = f"付款申请 {pr.id}" + (f"；预付款冲抵 {pr.prepayment_offset}" if pr.prepayment_offset > 0 else "")

    from app.services import capital_service as _cap
    txns: list[CapitalTransaction] = []
    if pool_splits:
        # 拆分支付：Σ拆分额 须等于实付现金；逐池校验余额并各生成一条流水
        total_split = sum(Decimal(str(s["amount"])) for s in pool_splits)
        if total_split != cash:
            raise BusinessError("BAD_REQUEST", f"拆分合计 {total_split} 须等于实付现金 {cash}", 400)
        for s in pool_splits:
            pool = s["pool"]
            amt = Decimal(str(s["amount"]))
            if pool not in _POOL_SOURCE:
                raise BusinessError("BAD_REQUEST",
                                    f"非法拆分资金池 {pool}（可选：LEASING 金租/BANK 银行/OWN 自有）", 400)
            if amt <= 0:
                raise BusinessError("BAD_REQUEST", "拆分金额必须 > 0", 400)
            _cap._assert_pool_sufficient(db, pr.project_id, pool, amt)
            txns.append(CapitalTransaction(
                project_id=pr.project_id, contract_id=pr.contract_id,
                source_type=_POOL_SOURCE[pool], direction=pr.direction,
                amount=amt, transaction_date=transaction_date, bank_id=bank_id,
                category="付款" if pr.direction == "OUT" else "收款",
                currency_code=pr.currency_code, settlement_rate=settlement_rate,
                base_amount=base_amount, note=note,
                idempotency_key=f"payreq:{pr.id}:{pool}", created_by=actor_id, pool=pool))
    else:
        txns.append(CapitalTransaction(
            project_id=pr.project_id, contract_id=pr.contract_id,
            source_type="自有资金", direction=pr.direction,
            amount=cash, transaction_date=transaction_date, bank_id=bank_id,
            category="付款" if pr.direction == "OUT" else "收款",
            currency_code=pr.currency_code, settlement_rate=settlement_rate,
            base_amount=base_amount,
            note=note,
            idempotency_key=f"payreq:{pr.id}", created_by=actor_id))
    db.add_all(txns)
    db.flush()
    txn = txns[0]  # 主流水（pr.capital_transaction_id 指向）
    if pr.prepayment_offset > 0:
        _apply_prepayment_offset(db, pr.project_id, pr.prepayment_offset, actor_id=actor_id)
    pr.status = "已付款"
    pr.capital_transaction_id = txn.id
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="CAPITAL_TXN", target_type="capital_transaction",
               target_id=txn.id,
               after_json={"payment_request_id": str(pr.id), "cash": str(cash),
                           "prepayment_offset": str(pr.prepayment_offset),
                           "pools": {t.pool: str(t.amount) for t in txns}})
    return txn


def _apply_prepayment_offset(db: Session, project_id, offset: Decimal, actor_id=None) -> None:
    """预付款冲抵：按设备剩余 FIFO 抵扣（视同结转）。create_request 已校验总额足够。"""
    rest = offset
    for d in db.execute(select(Device).where(
            Device.project_id == project_id, Device.prepayment_amount > 0,
            Device.prepayment_settled.is_(False)).order_by(Device.created_at)).scalars().all():
        if rest <= 0:
            break
        remaining = d.prepayment_amount - (d.prepayment_settled_amount or Decimal(0))
        take = min(remaining, rest)
        d.prepayment_settled_amount = (d.prepayment_settled_amount or Decimal(0)) + take
        if d.prepayment_settled_amount >= d.prepayment_amount:
            d.prepayment_settled_amount = d.prepayment_amount
            d.prepayment_settled = True
        rest -= take
    db.flush()


# ------------------------------ 核销（多对多 + 汇兑分摊至设备） ------------------------------

def settle(db: Session, *, txn_id, allocations: list[dict], actor_id=None) -> list[PaymentSettlement]:
    """核销：把一笔流水按 allocations 拆到多发票/多批次/多台设备。
    allocation = {amount, invoice_id?, batch_id?, device_id?}；Σamount 不得超流水额（允许部分核销/待认领）。
    发票核销满（旧链接+新核销行合计 ≥ 发票额）→ 已核销 + paid_date 兜底。
    外币发票（同币种非本币+双率）→ 汇兑损益按设备价值占比逐台拆分落核销行。
    """
    txn = db.get(CapitalTransaction, txn_id)
    if not txn or txn.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "资金流水不存在", 404)
    if not allocations:
        raise BusinessError("BAD_REQUEST", "核销明细分录不能为空", 400)
    total = sum((Decimal(str(a["amount"])) for a in allocations), Decimal(0))
    if total > txn.amount:
        raise BusinessError("BAD_REQUEST", f"核销合计 {total} 超流水金额 {txn.amount}", 400)

    rows: list[PaymentSettlement] = []
    for a in allocations:
        amt = Decimal(str(a["amount"]))
        if amt <= 0:
            raise BusinessError("BAD_REQUEST", "核销金额必须 > 0", 400)
        inv = None
        if a.get("invoice_id"):
            inv = db.get(Invoice, a["invoice_id"])
            if not inv or inv.deleted_at is not None:
                raise BusinessError("NOT_FOUND", f"发票不存在：{a['invoice_id']}", 404)
            # 方向校验：OUT 流水 → PAYABLE 发票；IN 流水 → RECEIVABLE 发票
            if txn.direction == "OUT" and inv.direction != "PAYABLE":
                raise BusinessError("VALIDATION_ERROR", "付款流水只能核销采购发票(PAYABLE)", 422)
            if txn.direction == "IN" and inv.direction != "RECEIVABLE":
                raise BusinessError("VALIDATION_ERROR", "收款流水只能核销销售发票(RECEIVABLE)", 422)
        row = PaymentSettlement(capital_transaction_id=txn.id, invoice_id=inv.id if inv else None,
                                batch_id=a.get("batch_id"), device_id=a.get("device_id"), amount=amt)
        db.add(row)
        rows.append(row)
    db.flush()

    # 发票满核销判定 + 汇兑损益分摊
    touched_invoices = {a["invoice_id"] for a in allocations if a.get("invoice_id")}
    for inv_id in touched_invoices:
        inv = db.get(Invoice, inv_id)
        _maybe_close_invoice(db, inv, txn)
        _book_fx_for_allocation(db, inv=inv, txn=txn, allocations=allocations, actor_id=actor_id)

    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="RECONCILE", target_type="capital_transaction",
               target_id=txn.id,
               after_json={"allocations": len(rows), "total": str(total)})
    return rows


def _invoice_matched(db: Session, invoice_id) -> Decimal:
    """已核销合计 = 旧 1:1 链接流水 + 新多对多核销行（与 matched_amount column_property 同口径）。"""
    legacy = db.execute(select(func.coalesce(func.sum(CapitalTransaction.amount), 0)).where(
        CapitalTransaction.invoice_id == invoice_id,
        CapitalTransaction.deleted_at.is_(None))).scalar() or Decimal(0)
    new = db.execute(select(func.coalesce(func.sum(PaymentSettlement.amount), 0)).where(
        PaymentSettlement.invoice_id == invoice_id,
        PaymentSettlement.deleted_at.is_(None))).scalar() or Decimal(0)
    return Decimal(legacy) + Decimal(new)


def _maybe_close_invoice(db: Session, inv: Invoice, txn: CapitalTransaction) -> None:
    if inv.status in ("已核销", "已红冲"):
        return
    if _invoice_matched(db, inv.id) >= inv.amount:
        inv.status = "已核销"
        if inv.paid_date is None:
            inv.paid_date = txn.transaction_date
        db.flush()


def _book_fx_for_allocation(db: Session, *, inv: Invoice, txn: CapitalTransaction,
                            allocations: list[dict], actor_id=None) -> None:
    """外币核销 → 汇兑损益落一条流水 + 按设备价值占比逐台拆 payment_settlements 行。
    计算口径与 W5-6 完全一致（compute_exchange_diff）；幂等 fx:{txn.id}:{inv.id}。"""
    if not inv.currency_code or inv.currency_code == base_currency_code(db):
        return
    if txn.currency_code != inv.currency_code:
        return
    if inv.invoice_rate is None or txn.settlement_rate is None:
        return
    alloc_amount = sum((Decimal(str(a["amount"])) for a in allocations
                        if a.get("invoice_id") == inv.id), Decimal(0))
    if alloc_amount <= 0:
        return
    existing = db.execute(select(CapitalTransaction.id).where(
        CapitalTransaction.idempotency_key == f"fx:{txn.id}:{inv.id}")).first()
    if existing is not None:
        return
    diff = compute_exchange_diff(alloc_amount, inv.invoice_rate, txn.settlement_rate)
    if diff == 0:
        return
    if inv.direction == "RECEIVABLE":
        direction = "OUT" if diff > 0 else "IN"
    else:
        direction = "IN" if diff > 0 else "OUT"
    contract = db.get(Contract, inv.contract_id)
    fx_txn = CapitalTransaction(
        project_id=contract.project_id if contract else txn.project_id,
        source_type="汇兑损益", direction=direction, amount=abs(diff),
        transaction_date=txn.transaction_date, contract_id=inv.contract_id,
        category="汇兑损益", idempotency_key=f"fx:{txn.id}:{inv.id}",
        note=f"核销汇兑损益：发票 {inv.invoice_no or inv.id} 开票率 {inv.invoice_rate} "
             f"vs 结算率 {txn.settlement_rate}，核销额外币 {alloc_amount} {inv.currency_code}",
        created_by=actor_id,
    )
    db.add(fx_txn)
    db.flush()
    # 按设备价值占比逐台拆核销行（设备取合同销售设备，无则项目设备）
    devices = db.execute(select(Device).where(
        Device.sales_contract_id == inv.contract_id, Device.deleted_at.is_(None))).scalars().all()
    if not devices and contract:
        devices = db.execute(select(Device).where(
            Device.project_id == contract.project_id, Device.deleted_at.is_(None),
            Device.purchase_value.is_not(None))).scalars().all()
    for dev_id, share in allocate_by_value([(d.id, d.purchase_value) for d in devices], abs(diff)):
        db.add(PaymentSettlement(capital_transaction_id=fx_txn.id, invoice_id=inv.id,
                                 device_id=dev_id, amount=share))
    db.flush()


# ------------------------------ 查询 ------------------------------

def list_requests(db: Session, project_id=None, status=None) -> list[PaymentRequest]:
    stmt = select(PaymentRequest).order_by(PaymentRequest.created_at.desc())
    if project_id:
        stmt = stmt.where(PaymentRequest.project_id == project_id)
    if status:
        stmt = stmt.where(PaymentRequest.status == status)
    return list(db.execute(stmt).scalars().all())


def list_settlements(db: Session, txn_id=None, invoice_id=None, device_id=None) -> list[PaymentSettlement]:
    stmt = select(PaymentSettlement).order_by(PaymentSettlement.created_at.desc())
    if txn_id:
        stmt = stmt.where(PaymentSettlement.capital_transaction_id == txn_id)
    if invoice_id:
        stmt = stmt.where(PaymentSettlement.invoice_id == invoice_id)
    if device_id:
        stmt = stmt.where(PaymentSettlement.device_id == device_id)
    return list(db.execute(stmt).scalars().all())
