from sqlalchemy.orm import Session

from app.models.project import Project


def create_project(
    db: Session,
    *,
    name: str,
    code: str | None = None,
    customer_id=None,
    total_investment=None,
    start_date=None,
    business_type=None,
    leasing_mode=None,
    parent_id=None,
    financing_plan=None,
) -> Project:
    p = Project(
        name=name,
        code=code,
        customer_id=customer_id,
        total_investment=total_investment,
        start_date=start_date,
        business_type=business_type,
        leasing_mode=leasing_mode,
        parent_id=parent_id,
        financing_plan=financing_plan,
    )
    db.add(p)
    db.flush()
    return p
