"""测试夹具：自动建 siegpu_test 库 + 表（幂等），每用例回滚。"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import Base  # 导入全部模型

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://siegpu:pw@db:5432/siegpu_test")


def _ensure_test_db():
    """确保 siegpu_test 库存在 + 用 schema.sql 建全部表（含 CHECK/触发器/索引）。"""
    import psycopg
    admin_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname='siegpu_test'")).fetchone()
        if not exists:
            conn.execute(text("CREATE DATABASE siegpu_test"))
    admin.dispose()
    # 每次重建 schema（干净 + 含 CHECK 约束）
    psycopg_url = TEST_DB_URL.replace("+psycopg", "")
    with psycopg.connect(psycopg_url) as conn:
        conn.autocommit = True
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        with open("/app/db/schema.sql") as f:
            conn.execute(f.read())
    return create_engine(TEST_DB_URL)


@pytest.fixture(scope="session")
def engine():
    eng = _ensure_test_db()
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    conn.close()
