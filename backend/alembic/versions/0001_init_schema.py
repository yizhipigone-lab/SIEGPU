"""init schema (19 tables, baseline) — 复用 db/schema.sql 作为 DDL 内容单一来源

Revision ID: 0001_init
Revises:
Create Date: 2026-07-31

说明：schema.sql 是 DDL 内容的真相源（已 PG16 ON_ERROR_STOP 实测）；
本迁移用 alembic 包一层执行它，取代 docker-entrypoint-initdb.d 自动加载。
后续加字段/表用 `alembic revision --autogenerate`（会检测列/索引/外键变更）。
"""
from pathlib import Path

from alembic import op

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema.sql"

DROP_ALL = """
DROP TABLE IF EXISTS
  idempotency_keys, audit_logs, assets, repayments, billings,
  delivery_stages, orders, capital_allocations, invoices, capital_transactions,
  leasing_nodes, leasing_processes, contracts, projects, banks, equipment_models,
  customers, suppliers, users
CASCADE;
DROP FUNCTION IF EXISTS set_updated_at();
"""


def upgrade() -> None:
    op.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(DROP_ALL)
