"""资产查询 + 折旧明细（复用 utils/depreciation 的 monthly_schedule）。"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.utils.depreciation import monthly_schedule
from app.utils.repayment_plan import add_months


def list_assets(db: Session, project_id=None):
    stmt = select(Asset).order_by(Asset.start_date.desc())
    if project_id:
        stmt = stmt.where(Asset.project_id == project_id)
    return db.execute(stmt).scalars().all()


def get_asset_or_404(db: Session, aid) -> Asset:
    a = db.get(Asset, aid)
    if not a or a.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "资产不存在", 404)
    return a


def depreciation_schedule(db: Session, aid) -> list[dict]:
    a = get_asset_or_404(db, aid)
    months = (a.end_date.year - a.start_date.year) * 12 + (a.end_date.month - a.start_date.month)
    sched = monthly_schedule(a.depreciable_value, months=months)
    return [
        {"period": i, "month": add_months(a.start_date, i - 1), "amount": sched[i - 1]}
        for i in range(1, months + 1)
    ]
