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
    """返回 (ΣIN, ΣOUT)，已自动过滤软删除（do_orm_execute 事件）。"""
    stmt = select(CapitalTransaction.direction, func.coalesce(func.sum(CapitalTransaction.amount), 0))
    if project_id:
        stmt = stmt.where(CapitalTransaction.project_id == project_id)
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
    return {
        "pool_balance": inn - out,
        "total_in": inn,
        "total_out": out,
        "by_source": by_source,
        "per_project": per_project,
    }


# ---------------- 写入 ----------------

def record_transaction(db: Session, *, created_by, **kw) -> CapitalTransaction:
    proj = db.get(Project, kw["project_id"])
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    txn = CapitalTransaction(created_by=created_by, **kw)
    db.add(txn)
    db.flush()  # 触发唯一约束等；commit 由 endpoint 负责
    return txn


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
        idempotency_key=f"reverse:{orig.id}",  # 每条原记录只能红冲一次（部分唯一索引兜底）
    )
    db.add(rev)
    db.flush()
    return rev


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
