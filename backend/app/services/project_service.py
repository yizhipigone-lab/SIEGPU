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
) -> Project:
    p = Project(
        name=name,
        code=code,
        customer_id=customer_id,
        total_investment=total_investment,
        start_date=start_date,
    )
    db.add(p)
    db.flush()
    return p
