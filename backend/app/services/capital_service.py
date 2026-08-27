"""资金池服务（一期核心）。对应设计书 §4.3/§5.1/§5.2。

事务范式（审计 TOP5）：service 只 flush（物化 id、触发约束），不 commit；
endpoint 统一 commit/rollback。红冲靠反向记录在 SUM 中自动抵消（NF3）。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, InsufficientAllocatable
from app.models.capital import CapitalAllocation, CapitalTransaction
from app.models.project import Project
from app.services.audit_service import audited


# ---------------- 查询 ----------------

def list_transactions(db: Session, project_id=None, direction=None, limit=100):
    stmt = (
        select(CapitalTransaction)
        .order_by(CapitalTransaction.transaction_date.desc(), CapitalTransaction.created_at.desc())
    )
    if project_id:
        stmt = stmt.where(CapitalTransaction.project_id == project_id)
    if direction:
        stmt = stmt.where(CapitalTransaction.direction == direction)
    stmt = stmt.limit(limit)
    return db.execute(stmt).scalars().all()


def _dir_sums(db: Session, project_id=None):
    """返回 (ΣIN, ΣOUT)，已自动过滤软删除（do_orm_execute 事件）。
    排除置换归还流水（归还流贷/归还自有 IN）：它们是原付款的冲销凭证，
    若计入会导致同笔现金双计虚增净头寸。"""
    stmt = select(CapitalTransaction.direction, func.coalesce(func.sum(CapitalTransaction.amount), 0))
    if project_id:
        stmt = stmt.where(CapitalTransaction.project_id == project_id)
    # 排除置换归还 IN（source_type IN ('归还流贷','归还自有') 且 direction='IN'）
    stmt = stmt.where(
        ~((CapitalTransaction.source_type.in_(['归还流贷', '归还自有'])) &
          (CapitalTransaction.direction == 'IN'))
    )
    stmt = stmt.group_by(CapitalTransaction.direction)
    inn = out = Decimal(0)
    for d, s in db.execute(stmt).all():
        s = Decimal(s)
        if d == "IN":
            inn += s
        else:
            out += s
    return inn, out


def project_net_position(db: Session, project_id) -> Decimal:
    inn, out = _dir_sums(db, project_id)
    return inn - out


def project_allocatable(db: Session, project_id) -> Decimal:
    """NF5：可调余额 = 净头寸正部（调配一调出即原子移走现金，net_position 已隐含）。"""
    np = project_net_position(db, project_id)
    return np if np > 0 else Decimal(0)


# ---------------- 四期 W4：资金池分池（按 pool 独立记账） ----------------

POOLS = ("OWN", "LEASING", "BANK", "PREPAY")
POOL_LABELS = {"OWN": "自有资金池", "LEASING": "金租池", "BANK": "银行池", "PREPAY": "预付款池(挂账)"}


def pool_balance(db: Session, project_id, pool: str) -> Decimal:
    """某项目某池余额 = ΣIN − ΣOUT（软删除过滤由 do_orm_execute 事件保证）。PREPAY 池=当前挂账预付额。"""
    inn, out = Decimal(0), Decimal(0)
    rows = db.execute(
        select(CapitalTransaction.direction, func.coalesce(func.sum(CapitalTransaction.amount), 0))
        .where(CapitalTransaction.project_id == project_id, CapitalTransaction.pool == pool)
        .group_by(CapitalTransaction.direction)
    ).all()
    for d, s in rows:
        if d == "IN":
            inn += Decimal(s)
        else:
            out += Decimal(s)
    return inn - out


def pools_by_project(db: Session, project_id) -> dict:
    """某项目 4 池余额：{pool: balance}。"""
    return {p: pool_balance(db, project_id, p) for p in POOLS}


def _assert_pool_sufficient(db: Session, project_id, pool: str, amount: Decimal) -> None:
    """OUT 前置校验：该池余额须 ≥ 金额（防超额支出/超挂账核销）。"""
    bal = pool_balance(db, project_id, pool)
    if amount > bal:
        raise BusinessError(
            "INSUFFICIENT_POOL",
            f"{POOL_LABELS.get(pool, pool)}余额不足：现有 {bal}，需 {amount}",
            400,
        )


def pool_by_project(db: Session) -> list[dict]:
    """分项目资金视图：净头寸 / 可调余额 / 在途调配 / 近30天收支。"""
    from datetime import date, timedelta
    projects = db.execute(select(Project).where(Project.deleted_at.is_(None))).scalars().all()
    recent = date.today() - timedelta(days=30)
    rows = []
    for p in projects:
        np = project_net_position(db, p.id)
        allocatable = float(np) if np > 0 else 0
        # 在途调配（借出未还）
        in_transit_q = db.execute(
            select(func.coalesce(func.sum(CapitalAllocation.amount), 0)).where(
                CapitalAllocation.from_project_id == p.id,
                CapitalAllocation.status.in_(["已调配", "逾期"]),
                CapitalAllocation.deleted_at.is_(None),
            )
        ).scalar() or 0
        # 近30天收支
        recent_in = db.execute(
            select(func.coalesce(func.sum(CapitalTransaction.amount), 0)).where(
                CapitalTransaction.project_id == p.id, CapitalTransaction.direction == "IN",
                CapitalTransaction.transaction_date >= recent, CapitalTransaction.deleted_at.is_(None),
            )
        ).scalar() or 0
        recent_out = db.execute(
            select(func.coalesce(func.sum(CapitalTransaction.amount), 0)).where(
                CapitalTransaction.project_id == p.id, CapitalTransaction.direction == "OUT",
                CapitalTransaction.transaction_date >= recent, CapitalTransaction.deleted_at.is_(None),
            )
        ).scalar() or 0
        rows.append({
            "project_id": str(p.id), "project_name": p.name,
            "net_position": float(np), "allocatable": allocatable,
            "in_transit": float(in_transit_q), "recent_30d_in": float(recent_in),
            "recent_30d_out": float(recent_out),
        })
    return rows


def list_allocations(db: Session, project_id=None):
    stmt = select(CapitalAllocation).order_by(CapitalAllocation.created_at.desc())
    if project_id:
        stmt = stmt.where(
            (CapitalAllocation.from_project_id == project_id) |
            (CapitalAllocation.to_project_id == project_id)
        )
    return db.execute(stmt).scalars().all()


def pool_summary(db: Session) -> dict:
    inn, out = _dir_sums(db)
    # 按来源拆分
    src_rows = db.execute(
        select(
            CapitalTransaction.source_type,
            CapitalTransaction.direction,
            func.coalesce(func.sum(CapitalTransaction.amount), 0),
        ).group_by(CapitalTransaction.source_type, CapitalTransaction.direction)
    ).all()
    by_source: dict[str, dict] = {}
    for st, d, s in src_rows:
        bucket = by_source.setdefault(st, {"in": Decimal(0), "out": Decimal(0)})
        s = Decimal(s)
        if d == "IN":
            bucket["in"] += s
        else:
            bucket["out"] += s
    for b in by_source.values():
        b["net"] = b["in"] - b["out"]
    # 各项目净头寸
    proj_rows = db.execute(
        select(
            CapitalTransaction.project_id,
            CapitalTransaction.direction,
            func.coalesce(func.sum(CapitalTransaction.amount), 0),
        ).group_by(CapitalTransaction.project_id, CapitalTransaction.direction)
    ).all()
    per: dict = {}
    for pid, d, s in proj_rows:
        bucket = per.setdefault(str(pid), {"in": Decimal(0), "out": Decimal(0)})
        s = Decimal(s)
        if d == "IN":
            bucket["in"] += s
        else:
            bucket["out"] += s
    per_project = [
        {"project_id": k, "in": v["in"], "out": v["out"], "net_position": v["in"] - v["out"]}
        for k, v in per.items()
    ]
    # 四期 W4：按资金池拆分（全局，跨项目 Σ）
    pool_rows = db.execute(
        select(
            CapitalTransaction.pool,
            CapitalTransaction.direction,
            func.coalesce(func.sum(CapitalTransaction.amount), 0),
        ).group_by(CapitalTransaction.pool, CapitalTransaction.direction)
    ).all()
    by_pool: dict[str, dict] = {p: {"label": POOL_LABELS[p], "in": Decimal(0), "out": Decimal(0)} for p in POOLS}
    for pl, d, s in pool_rows:
        b = by_pool.setdefault(pl, {"label": POOL_LABELS.get(pl, pl), "in": Decimal(0), "out": Decimal(0)})
        s = Decimal(s)
        if d == "IN":
            b["in"] += s
        else:
            b["out"] += s
    for b in by_pool.values():
        b["net"] = b["in"] - b["out"]
    return {
        "pool_balance": inn - out,
        "total_in": inn,
        "total_out": out,
        "by_source": by_source,
        "per_project": per_project,
        "by_pool": by_pool,
    }


# ---------------- 写入 ----------------

@audited(action="CAPITAL_TXN", target_type="capital_transaction",
         fields=["source_type", "direction", "amount"])
def record_transaction(db: Session, *, created_by, **kw) -> CapitalTransaction:
    proj = db.get(Project, kw["project_id"])
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    # 注：通用「记一笔」不强制池余额（财务可能要记调整/期初）；池余额硬校验放在专门的支出动作
    # （付款按池拆分 disburse、预付、还银行 repay_bank）里，用 _assert_pool_sufficient。
    txn = CapitalTransaction(created_by=created_by, **kw)
    db.add(txn)
    db.flush()  # 触发唯一约束等；commit 由 endpoint 负责（审计由 @audited 声明式留痕）
    return txn


# ---------------- 四期 W4：资金池专用动作（记借款/还银行/预付/退回/核销） ----------------

def _log_pool(db, user_id, action, txn, extra=None):
    """#4 渐进豁免：record_prepayment / refund_prepayment 返回双实体、审计带 side
    区分两路流水——计算型 payload 不适合声明式装饰器，保留函数体留痕（audit_service
    「用法二」），其余资金池动作已全部迁移 @audited。"""
    from app.services import audit_service as _audit
    after = {"source_type": txn.source_type, "direction": txn.direction, "pool": txn.pool,
             "amount": str(txn.amount)}
    if extra:
        after.update(extra)
    _audit.log(db, user_id=user_id, action=action, target_type="capital_transaction",
               target_id=txn.id, after_json=after)


@audited(action="CAPITAL_TXN", target_type="capital_transaction",
         fields=["source_type", "direction", "pool", "amount"])
def record_bank_loan(db: Session, *, project_id, amount, transaction_date, created_by,
                     bank_id=None, note=None, idempotency_key=None) -> CapitalTransaction:
    """记一笔银行借款 → 银行池 IN（pool=BANK）。"""
    proj = db.get(Project, project_id)
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    txn = CapitalTransaction(project_id=project_id, source_type="银行流贷", direction="IN",
                             amount=amount, transaction_date=transaction_date, bank_id=bank_id,
                             category="银行借款", note=note, created_by=created_by, pool="BANK",
                             idempotency_key=idempotency_key or f"bankloan:{uuid.uuid4()}")
    db.add(txn)
    db.flush()
    return txn


@audited(action="CAPITAL_TXN", target_type="capital_transaction",
         fields=["source_type", "direction", "pool", "amount"])
def repay_bank(db: Session, *, project_id, amount, transaction_date, created_by,
               bank_id=None, note=None, idempotency_key=None) -> CapitalTransaction:
    """还银行 → 银行池 OUT（前置校验银行池余额充足）。银行池=持有的银行借款余额，还款即减少。"""
    amount = Decimal(str(amount))
    _assert_pool_sufficient(db, project_id, "BANK", amount)
    txn = CapitalTransaction(project_id=project_id, source_type="归还银行", direction="OUT",
                             amount=amount, transaction_date=transaction_date, bank_id=bank_id,
                             category="还银行", note=note, created_by=created_by, pool="BANK",
                             idempotency_key=idempotency_key or f"repaybank:{uuid.uuid4()}")
    db.add(txn)
    db.flush()
    return txn


def record_prepayment(db: Session, *, project_id, amount, transaction_date, created_by,
                      contract_id=None, from_pool="BANK", note=None, idempotency_key=None):
    """预付：现金池(from_pool) OUT + 预付款池(挂账) IN。返回 (现金流水, 挂账流水)。"""
    amount = Decimal(str(amount))
    if from_pool == "PREPAY":
        raise BusinessError("BAD_REQUEST", "预付款不能从预付款池支出", 400)
    if from_pool not in POOLS:
        raise BusinessError("BAD_REQUEST", f"非法资金池 {from_pool}", 400)
    _assert_pool_sufficient(db, project_id, from_pool, amount)
    base = idempotency_key or f"prepay:{uuid.uuid4()}"
    cash_out = CapitalTransaction(project_id=project_id, source_type="预付", direction="OUT",
                                  amount=amount, transaction_date=transaction_date, contract_id=contract_id,
                                  category="预付", note=note, created_by=created_by, pool=from_pool,
                                  idempotency_key=f"{base}:cash")
    hang_in = CapitalTransaction(project_id=project_id, source_type="预付", direction="IN",
                                 amount=amount, transaction_date=transaction_date, contract_id=contract_id,
                                 category="预付挂账", note=note, created_by=created_by, pool="PREPAY",
                                 idempotency_key=f"{base}:hang")
    db.add_all([cash_out, hang_in])
    db.flush()
    _log_pool(db, created_by, "CAPITAL_TXN", cash_out, {"side": "cash"})
    _log_pool(db, created_by, "CAPITAL_TXN", hang_in, {"side": "hang"})
    return cash_out, hang_in


def refund_prepayment(db: Session, *, project_id, amount, transaction_date, created_by,
                      to_pool="BANK", note=None, idempotency_key=None):
    """预付退回（金租放款后供应商退回）：预付款池(挂账) OUT + 现金回到指定池(to_pool) IN。"""
    amount = Decimal(str(amount))
    if to_pool == "PREPAY":
        raise BusinessError("BAD_REQUEST", "退回不能回到预付款池", 400)
    _assert_pool_sufficient(db, project_id, "PREPAY", amount)  # 挂账余额须够
    base = idempotency_key or f"prepay-refund:{uuid.uuid4()}"
    hang_out = CapitalTransaction(project_id=project_id, source_type="预付", direction="OUT",
                                  amount=amount, transaction_date=transaction_date,
                                  category="预付退回", note=note, created_by=created_by, pool="PREPAY",
                                  idempotency_key=f"{base}:hang")
    cash_in = CapitalTransaction(project_id=project_id, source_type="预付", direction="IN",
                                 amount=amount, transaction_date=transaction_date,
                                 category="预付退回", note=note, created_by=created_by, pool=to_pool,
                                 idempotency_key=f"{base}:cash")
    db.add_all([hang_out, cash_in])
    db.flush()
    _log_pool(db, created_by, "CAPITAL_TXN", hang_out, {"side": "hang"})
    _log_pool(db, created_by, "CAPITAL_TXN", cash_in, {"side": "cash"})
    return hang_out, cash_in


@audited(action="CAPITAL_TXN", target_type="capital_transaction",
         fields=["source_type", "direction", "pool", "amount"])
def offset_prepayment(db: Session, *, project_id, amount, transaction_date, created_by,
                      invoice_id=None, contract_id=None, note=None, idempotency_key=None) -> CapitalTransaction:
    """预付核销（采购验收拿到发票）：预付款池(挂账) OUT，抵减应付（不涉现金）。"""
    amount = Decimal(str(amount))
    _assert_pool_sufficient(db, project_id, "PREPAY", amount)  # 挂账余额须够
    hang_out = CapitalTransaction(project_id=project_id, source_type="预付", direction="OUT",
                                  amount=amount, transaction_date=transaction_date,
                                  contract_id=contract_id, invoice_id=invoice_id,
                                  category="预付核销", note=note, created_by=created_by, pool="PREPAY",
                                  idempotency_key=idempotency_key or f"prepay-offset:{uuid.uuid4()}")
    db.add(hang_out)
    db.flush()
    return hang_out


@audited(action="ALLOCATE", target_type="capital_allocation",
         fields=["from_project_id", "to_project_id", "amount"])
def allocate(
    db: Session,
    *,
    approved_by,
    from_project_id,
    to_project_id,
    amount,
    allocation_date: date,
    expected_return_date: date | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> CapitalAllocation:
    if from_project_id == to_project_id:
        raise BusinessError("BAD_REQUEST", "调出与调入项目不能相同", 400)
    for pid in (from_project_id, to_project_id):
        proj = db.get(Project, pid)
        if not proj or proj.deleted_at is not None:
            raise BusinessError("NOT_FOUND", "项目不存在", 404)
    # NF5：可调余额前置校验
    have = project_allocatable(db, from_project_id)
    if amount > have:
        raise InsufficientAllocatable(need=amount, have=have)

    base = idempotency_key or f"allocate:{uuid.uuid4()}"
    # NF1：两条流水用不同幂等键（OUT/IN 后缀），整笔幂等交通用层 + allocations 约束
    out_txn = CapitalTransaction(
        project_id=from_project_id, source_type="调配", direction="OUT",
        amount=amount, transaction_date=allocation_date, category="调配",
        idempotency_key=f"{base}:OUT", note=reason, created_by=approved_by,
    )
    in_txn = CapitalTransaction(
        project_id=to_project_id, source_type="调配", direction="IN",
        amount=amount, transaction_date=allocation_date, category="调配",
        idempotency_key=f"{base}:IN", note=reason, created_by=approved_by,
    )
    db.add_all([out_txn, in_txn])
    db.flush()  # 物化 id；三表写入同事务，由 endpoint 一次性 commit（TOP5 原子性）
    alloc = CapitalAllocation(
        from_project_id=from_project_id, to_project_id=to_project_id,
        amount=amount, allocation_date=allocation_date,
        expected_return_date=expected_return_date, reason=reason,
        status="已调配", approved_by=approved_by,
        out_txn_id=out_txn.id, in_txn_id=in_txn.id,
    )
    db.add(alloc)
    db.flush()
    return alloc


def reverse_transaction(db: Session, *, txn_id, reversed_by, note: str | None = None) -> CapitalTransaction:
    """红冲：不改不删原记录，新建等额反向记录；在 SUM 中自动抵消（NF3）。"""
    orig = db.get(CapitalTransaction, txn_id)
    if not orig or orig.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "原流水不存在", 404)
    if orig.is_reversal:
        raise BusinessError("BAD_REQUEST", "反向记录不可再红冲", 400)  # NW7 防呆
    # 原记录是否已有红冲（查指向它的反向记录）
    exists = db.execute(
        select(CapitalTransaction.id).where(
            CapitalTransaction.reversal_of_id == orig.id,
            CapitalTransaction.is_reversal.is_(True),
        )
    ).first()
    if exists:
        raise BusinessError("DUPLICATE", "原流水已存在红冲记录", 409)
    rev = CapitalTransaction(
        project_id=orig.project_id,
        source_type=orig.source_type,
        direction="OUT" if orig.direction == "IN" else "IN",  # 方向相反
        amount=orig.amount,
        transaction_date=orig.transaction_date,
        category=orig.category or "红冲",
        note=note or "红冲",
        bank_id=orig.bank_id,
        contract_id=orig.contract_id,
        leasing_process_id=orig.leasing_process_id,
        reversal_of_id=orig.id,
        is_reversal=True,
        created_by=reversed_by,
        pool=orig.pool,  # 四期 W4：红冲须同池反向，各池余额才能在 SUM 中自动抵消
        idempotency_key=f"reverse:{orig.id}",  # 每条原记录只能红冲一次（部分唯一索引兜底）
    )
    db.add(rev)
    db.flush()
    # #4 渐进豁免：审计对象=被红冲的原流水（entity_id 语义），装饰器只读返回实体，保留函数体留痕
    from app.services import audit_service as _audit4
    _audit4.log(db, user_id=reversed_by, action="REVERSE", target_type="capital_transaction",
                target_id=orig.id, after_json={"reversal_id": str(rev.id), "amount": str(orig.amount)})
    return rev


@audited(action="ALLOCATE_RETURN", target_type="capital_allocation",
         fields=["status", "actual_return_date", "amount"])
def return_allocation(db: Session, *, allocation_id, returned_by, return_date) -> CapitalAllocation:
    """调配归还：反向 2 条流水（B 出 / A 入，source=调配归还）+ 状态→已归还。净 0。"""
    alloc = db.get(CapitalAllocation, allocation_id)
    if not alloc or alloc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "调配记录不存在", 404)
    if alloc.status not in ("已调配", "逾期"):
        raise BusinessError("ILLEGAL_TRANSITION", f"调配状态 {alloc.status} 不可归还", 409)
    base = f"allocate-return:{alloc.id}"
    out_txn = CapitalTransaction(  # B 调出
        project_id=alloc.to_project_id, source_type="调配归还", direction="OUT",
        amount=alloc.amount, transaction_date=return_date, category="调配归还",
        idempotency_key=f"{base}:OUT", created_by=returned_by,
    )
    in_txn = CapitalTransaction(  # A 收回
        project_id=alloc.from_project_id, source_type="调配归还", direction="IN",
        amount=alloc.amount, transaction_date=return_date, category="调配归还",
        idempotency_key=f"{base}:IN", created_by=returned_by,
    )
    db.add_all([out_txn, in_txn])
    db.flush()
    alloc.status = "已归还"
    alloc.actual_return_date = return_date
    db.flush()
    return alloc
