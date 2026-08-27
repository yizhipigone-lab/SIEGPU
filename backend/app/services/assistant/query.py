"""通用安全查询（通用探索层的执行器）：LLM 自己组条件找答案，但永远拼不出裸 SQL。

安全边界（财务系统红线）：
1. 实体白名单：只能查 datadict.ENTITIES 里的 18 张业务表（users/audit_logs 等不开放）；
2. 字段白名单：filter/group/order/fields 必须在该实体允许字段内，敏感列已排除；
3. 操作白名单：只读 SELECT，聚合仅 count/sum/avg，比较仅 eq/ne/like/gt/ge/lt/le/in/isnull；
4. LIMIT 强制 ≤100；软删过滤强制追加（deleted_at IS NULL）；
5. 全部值走 SQLAlchemy 参数化绑定——注入面只剩「参数值」，拼不了语法。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.assistant import datadict

MAX_LIMIT = 100
_OPS = ("eq", "ne", "like", "gt", "ge", "lt", "le", "in", "isnull")
_AGG = ("count", "sum", "avg")


def _ser(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return str(v)
    return v


def _col(entity: str, field: str):
    """字段白名单解析；不合法返回 None。"""
    if field not in datadict.allowed_fields(entity):
        return None
    return getattr(datadict.ENTITIES[entity]["model"], field, None)


def _apply_filter(stmt, col, op: str, value: Any):
    if op == "eq":
        return stmt.where(col == value)
    if op == "ne":
        return stmt.where(col != value)
    if op == "like":
        return stmt.where(col.ilike(f"%{value}%"))
    if op == "gt":
        return stmt.where(col > value)
    if op == "ge":
        return stmt.where(col >= value)
    if op == "lt":
        return stmt.where(col < value)
    if op == "le":
        return stmt.where(col <= value)
    if op == "in" and isinstance(value, list):
        return stmt.where(col.in_(value))
    if op == "isnull":
        return stmt.where(col.is_(None) if value else col.is_not(None))
    raise ValueError(f"不支持的比较操作: {op}")


def query_data(db: Session, entity: str, filters: list[dict] | None = None,
               fields: list[str] | None = None, group_by: list[str] | None = None,
               metrics: list[dict] | None = None, order_by: str | None = None,
               limit: int = 20) -> dict:
    """结构化只读查询。返回 {rows:[...]} 或聚合结果；任何白名单违规 → ValueError（上层标【缺】）。"""
    if entity not in datadict.ENTITIES:
        raise ValueError(f"实体「{entity}」不在白名单（可用 describe_schema 查看全部实体）")
    model = datadict.ENTITIES[entity]["model"]
    limit = max(1, min(int(limit or 20), MAX_LIMIT))

    # —— 聚合模式：group_by + metrics ——
    if metrics or group_by:
        groups, aggs = [], []
        for f in (group_by or []):
            c = _col(entity, f)
            if c is None:
                raise ValueError(f"group_by 字段「{f}」不在白名单")
            groups.append(c)
        for m in (metrics or [{"func": "count", "field": "id"}]):
            fn, fld = m.get("func"), m.get("field", "id")
            if fn not in _AGG:
                raise ValueError(f"聚合函数「{fn}」不支持（仅 count/sum/avg）")
            c = _col(entity, fld)
            if c is None:
                raise ValueError(f"聚合字段「{fld}」不在白名单")
            aggs.append(getattr(func, fn)(c).label(f"{fn}_{fld}"))
        if not aggs:
            aggs.append(func.count(model.id).label("count_id"))
        stmt = select(*groups, *aggs).group_by(*groups) if groups else select(*aggs)
    else:
        # —— 行查询模式 ——
        cols = []
        for f in (fields or []):
            c = _col(entity, f)
            if c is None:
                raise ValueError(f"查询字段「{f}」不在白名单")
            cols.append(c)
        stmt = select(*(cols or [model]))

    # 软删强制过滤（聚合 select(func...) 不走 ORM 实体事件，必须显式加）
    stmt = stmt.where(model.deleted_at.is_(None))

    for f in (filters or []):
        fld, op, val = f.get("field"), f.get("op", "eq"), f.get("value")
        if op not in _OPS:
            raise ValueError(f"比较操作「{op}」不支持")
        c = _col(entity, fld or "")
        if c is None:
            raise ValueError(f"过滤字段「{fld}」不在白名单")
        stmt = _apply_filter(stmt, c, op, val)

    if order_by:
        parts = order_by.strip().split()
        c = _col(entity, parts[0])
        if c is None:
            raise ValueError(f"排序字段「{parts[0]}」不在白名单")
        stmt = stmt.order_by(c.desc() if len(parts) > 1 and parts[1].lower() == "desc" else c)

    stmt = stmt.limit(limit)
    rows = db.execute(stmt).mappings().all() if (metrics or group_by or fields) else None
    if rows is not None:
        return {"entity": entity, "count": len(rows),
                "rows": [{k: _ser(v) for k, v in r.items()} for r in rows]}
    # 整模型行查询：转 dict
    out = []
    for obj in db.execute(stmt).scalars().all():
        out.append({c.name: _ser(getattr(obj, c.name))
                    for c in model.__table__.columns
                    if c.name not in datadict.DENY_FIELDS and c.name != "deleted_at"})
    return {"entity": entity, "count": len(out), "rows": out}