"""主数据 CRUD 测试（含软删除默认过滤、枚举/CHECK）。

注意：每个预期 IntegrityError 独占一个用例且作为最后一步——PG 下一次 flush 报错会把事务置为 aborted，
之后同用例内的操作会失败（fixture 仅在用例末尾回滚）。
"""
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BusinessError
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.services import master_service as svc


def test_supplier_create_list_softdelete(db):
    s = svc.create_entity(db, Supplier, {"name": "金租X", "type": "资金供应商"})
    assert s.id is not None
    assert len(svc.list_entities(db, Supplier)) == 1
    svc.soft_delete_entity(db, Supplier, s.id)
    assert len(svc.list_entities(db, Supplier)) == 0  # 软删除后默认查询过滤
    with pytest.raises(BusinessError):
        svc.get_entity_or_404(db, Supplier, s.id)


def test_supplier_type_check_constraint(db):
    with pytest.raises(IntegrityError):
        svc.create_entity(db, Supplier, {"name": "X", "type": "供应商"})  # type 非法


def test_equipment_create_ok(db):
    e = svc.create_entity(db, EquipmentModel, {"name": "H100", "category": "大卡", "gpu_count": 8})
    assert e.category == "大卡" and e.gpu_count == 8


def test_equipment_category_check(db):
    with pytest.raises(IntegrityError):
        svc.create_entity(db, EquipmentModel, {"name": "X", "category": "其他"})  # category 非法


def test_bank_create_ok(db):
    b = svc.create_entity(db, Bank, {"name": "工行", "credit_line": Decimal("1000000"), "annual_rate": Decimal("0.0435")})
    assert b.annual_rate == Decimal("0.04350000")  # NUMERIC(10,8) 存小数


def test_bank_rate_check(db):
    with pytest.raises(IntegrityError):
        svc.create_entity(db, Bank, {"name": "X", "annual_rate": Decimal("1.5")})  # rate >=1，CHECK 拦截


def test_customer_update(db):
    c = svc.create_entity(db, Customer, {"name": "客户A", "industry": "AI"})
    svc.update_entity(db, Customer, c.id, {"industry": "算力", "credit_rating": "AAA"})
    fresh = svc.get_entity_or_404(db, Customer, c.id)
    assert fresh.industry == "算力" and fresh.credit_rating == "AAA"
