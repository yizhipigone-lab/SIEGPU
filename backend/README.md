# SIEGPU ERP — Backend

FastAPI + SQLAlchemy 2.0 + PostgreSQL 16。对应设计书 `docs/superpowers/specs/2026-07-30-siegpu-erp-design-v2.md`。

## 目录

```
app/
  main.py              FastAPI 入口（health / auth / projects 桩）
  seed.py              种子用户（admin/admin123, cfo/cfo123）
  core/                config · db · security(JWT/bcrypt) · deps(RBAC) · exceptions
  models/              19 张表 SQLAlchemy 模型（与 db/schema.sql 对齐）
  utils/               纯算法：billing · depreciation · repayment_plan · reconcile · capital
  api/v1/endpoints/    路由（薄层）
  tests/               算法单测
db/schema.sql          完整 DDL（19 表，PG16 实测零报错）
alembic/               迁移骨架
```

## 本地开发

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
# 跑算法单测（无需 DB）
PYTHONPATH=. python -m pytest app/tests/ -v
# 起服务（需 DB）
uvicorn app.main:app --reload
```

## 算法单测

`app/tests/test_algorithms.py` 覆盖设计书 §5 关键公式（17 用例全绿）：计费首月按比例/价税分离、折旧月化与尾差、还款计划等额本息/等额本金（Σ本金=放款额）、可调余额（NF5）、对账与超开（NF4）。

## 迁移策略

- 本骨架用 `db/schema.sql` 经 PG `docker-entrypoint-initdb.d` 首次初始化建表（compose 已挂载）。
- 生产改用 Alembic：移除 compose 中 schema.sql 挂载，改为 `alembic revision --autogenerate -m init && alembic upgrade head`；与 schema.sql 二选一，勿混用。
