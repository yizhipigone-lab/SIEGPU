from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings

# 池容量：默认 size=5/overflow=10=最大 15 连接，扛不住全量 e2e 多 worker 并发
# （Playwright 默认按 CPU 半数开 worker，每 worker 并发发 API → QueuePool 耗尽 → 登录 504/超时）。
# 调到 size=20/overflow=20=40 上限；PostgreSQL 默认 max_connections=100，留余量且不触顶。
engine = create_engine(
    settings.database_url, pool_pre_ping=True, future=True,
    pool_size=20, max_overflow=20, pool_timeout=30,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
