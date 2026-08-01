"""资金置换引擎 — 金租放款时自动扫描未置换付款并生成归还流水。"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.capital import CapitalTransaction
from app.models.funding import FundingReplacement


def execute_replacement(db: Session, *, project_id: uuid.UUID,
                        leasing_process_id: uuid.UUID,
                        disbursement_amount: Decimal,
                        disbursement_date: date,
                        created_by: uuid.UUID) -> list[FundingReplacement]:
    """扫描项目下未置换的流贷/自有付款，按时间顺序匹配置换。

    返回生成的置换记录列表（可能为空）。
    置换结果由调用方在同一个 DB 事务内 commit。
    """
    remaining = disbursement_amount
    if remaining <= 0:
        return []

    # 扫描待置换付款：is_replaced=FALSE + replaced_amount < amount
    stmt = (
        select(CapitalTransaction)
        .where(
            CapitalTransaction.project_id == project_id,
            CapitalTransaction.direction == "OUT",
            CapitalTransaction.source_type.in_(["银行流贷", "自有资金"]),
            CapitalTransaction.is_replaced == False,
            CapitalTransaction.replaced_amount < CapitalTransaction.amount,
            CapitalTransaction.deleted_at.is_(None),
        )
        .order_by(CapitalTransaction.transaction_date.asc())
    )
    candidates = db.execute(stmt).scalars().all()

    replacements: list[FundingReplacement] = []
    for txn in candidates:
        if remaining <= 0:
            break
        outstanding = txn.amount - txn.replaced_amount
        replace_amt = min(outstanding, remaining)

        # 生成归还流水
        source_label = "归还流贷" if txn.source_type == "银行流贷" else "归还自有"
        repay_txn = CapitalTransaction(
            project_id=project_id,
            source_type=source_label,
            direction="IN",
            amount=replace_amt,
            transaction_date=disbursement_date,
            category="置换归还",
            note=f"金租放款置换：原付款 {txn.id}",
            created_by=created_by,
            contract_id=txn.contract_id,
            leasing_process_id=leasing_process_id,
        )
        db.add(repay_txn)
        db.flush()

        # 更新原付款
        txn.replaced_amount += replace_amt
        if txn.replaced_amount >= txn.amount:
            txn.is_replaced = True

        # 置换记录
        fr = FundingReplacement(
            project_id=project_id,
            leasing_process_id=leasing_process_id,
            original_txn_id=txn.id,
            replacement_txn_id=repay_txn.id,
            amount=replace_amt,
            source_type_replaced=txn.source_type,
            replacement_date=disbursement_date,
        )
        db.add(fr)
        db.flush()
        replacements.append(fr)
        remaining -= replace_amt

    return replacements


def list_replacements(db: Session, *, project_id: uuid.UUID | None = None,
                      skip=0, limit=100) -> list[FundingReplacement]:
    stmt = select(FundingReplacement).where(FundingReplacement.deleted_at.is_(None))
    if project_id:
        stmt = stmt.where(FundingReplacement.project_id == project_id)
    stmt = stmt.order_by(FundingReplacement.created_at.desc()).offset(skip).limit(limit)
    return db.execute(stmt).scalars().all()
