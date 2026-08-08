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
    # W5-6：未激活资产卡（operation_status=已转固未运营）折旧字段为 None，无明细可算
    if (a.start_date is None or a.end_date is None or a.depreciable_value is None):
        raise BusinessError("BAD_REQUEST", "资产尚未进入运营（未点亮验收），无折旧明细", 400)
    months = (a.end_date.year - a.start_date.year) * 12 + (a.end_date.month - a.start_date.month)
    sched = monthly_schedule(a.depreciable_value, months=months)
    return [
        {"period": i, "month": add_months(a.start_date, i - 1), "amount": sched[i - 1]}
        for i in range(1, months + 1)
    ]
