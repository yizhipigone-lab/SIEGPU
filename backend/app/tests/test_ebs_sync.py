"""EBS 同步服务测试（二期 W1-2）：映射 CRUD + Mock 出站 + 幂等 + 版本 + 映射转换 + 重试。

服务层测试（端点薄，端到端在 e2e 覆盖）。db 夹具每用例回滚，互不污染。
"""
import uuid

import pytest

from app.models.ebs import EbsFieldMapping, EbsSyncLog
from app.models.master import Customer
from app.services import ebs_sync_service as svc
from app.services import master_service
from sqlalchemy import select


# ------------------------------ 字段映射 CRUD ------------------------------

def test_mapping_crud(db):
    m = svc.create_mapping(db, {"entity_type": "customer", "siegpu_field": "name",
                                "ebs_field": "CUSTOMER_NAME", "transform_rule": "direct"})
    assert m.id is not None
    assert len(svc.list_mappings(db)) == 1
    assert len(svc.list_mappings(db, "customer")) == 1
    assert len(svc.list_mappings(db, "invoice")) == 0  # 按类型过滤

    m2 = svc.update_mapping(db, m.id, {"ebs_field": "CUST_NAME"})
    assert m2.ebs_field == "CUST_NAME"

    assert svc.soft_delete_mapping(db, m.id) is True
    assert len(svc.list_mappings(db)) == 0  # 软删除后默认查询过滤
    assert svc.soft_delete_mapping(db, m.id) is False  # 已删，再删不命中


def test_mapping_duplicate_raises(db):
    svc.create_mapping(db, {"entity_type": "customer", "siegpu_field": "name", "ebs_field": "X"})
    with pytest.raises(ValueError):  # 同 entity_type+siegpu_field 重复 → 服务层守卫（不触发 DB 唯一约束）
        svc.create_mapping(db, {"entity_type": "customer", "siegpu_field": "name", "ebs_field": "Y"})


def test_mapping_softdeleted_then_recreate_ok(db):
    """软删除后同名映射可重建（部分唯一索引 + 服务层查询都只看活跃行）。"""
    m = svc.create_mapping(db, {"entity_type": "invoice", "siegpu_field": "amount", "ebs_field": "AMT"})
    svc.soft_delete_mapping(db, m.id)
    m2 = svc.create_mapping(db, {"entity_type": "invoice", "siegpu_field": "amount", "ebs_field": "AMT2"})
    assert m2.id != m.id  # 重建成功，新 id


# ------------------------------ 版本化 ------------------------------

def test_compute_version_stable_and_sensitive():
    v1 = svc._compute_version({"a": 1, "b": 2})
    assert v1 == svc._compute_version({"b": 2, "a": 1})  # 键序无关 → 同版本
    assert v1 != svc._compute_version({"a": 1, "b": 3})  # 内容变 → 版本变
    assert len(v1) == 16  # sha256 前 16 字符


# ------------------------------ 出站 + 幂等 ------------------------------

def test_sync_creates_mock_success_log(db):
    c = master_service.create_entity(db, Customer, {"name": "EBS测试客户"})
    res = svc.sync_customer(db, c.id)
    assert res is not None
    assert res["status"] == "MOCK_SUCCESS"
    assert res["ebs_reference"].startswith("MOCK-EBS-")
    assert res["entity_type"] == "customer"
    assert res["entity_id"] == str(c.id)
    assert res["skipped"] is False
    assert res["request_payload"]["name"] == "EBS测试客户"  # 业务字段进载荷


def test_sync_idempotent_second_skipped(db):
    c = master_service.create_entity(db, Customer, {"name": "幂等客户"})
    first = svc.sync_customer(db, c.id)
    assert first["skipped"] is False
    second = svc.sync_customer(db, c.id)  # 同内容同版本 → 命中幂等，跳过
    assert second["skipped"] is True
    assert second["id"] == first["id"]  # 返回的是同一条 log
    # 只写了 1 条 log（幂等跳过不新建）
    n = len(db.execute(select(EbsSyncLog).where(EbsSyncLog.entity_id == str(c.id))).all())
    assert n == 1


def test_sync_content_change_breaks_idempotency(db):
    """改了业务字段 → 版本变 → 不再幂等，写新 log。"""
    c = master_service.create_entity(db, Customer, {"name": "原客户"})
    svc.sync_customer(db, c.id)
    master_service.update_entity(db, Customer, c.id, {"name": "改名客户"})
    res = svc.sync_customer(db, c.id)
    assert res["skipped"] is False  # 内容变 → 新版本 → 新 log
    n = len(db.execute(select(EbsSyncLog).where(EbsSyncLog.entity_id == str(c.id))).all())
    assert n == 2


# ------------------------------ 字段映射转换 ------------------------------

def test_mapping_direct_rename_applied(db):
    svc.create_mapping(db, {"entity_type": "customer", "siegpu_field": "name",
                            "ebs_field": "CUSTOMER_NAME", "transform_rule": "direct"})
    c = master_service.create_entity(db, Customer, {"name": "张三"})
    res = svc.sync_customer(db, c.id)
    payload = res["request_payload"]
    assert payload["CUSTOMER_NAME"] == "张三"  # 重命名生效
    assert "name" not in payload  # 原字段名不再出现（已被映射消费）


def test_mapping_constant_applied(db):
    svc.create_mapping(db, {"entity_type": "customer", "siegpu_field": "name",
                            "ebs_field": "SOURCE_SYSTEM", "transform_rule": "constant",
                            "transform_config": {"value": "SIEGPU"}})
    c = master_service.create_entity(db, Customer, {"name": "李四"})
    res = svc.sync_customer(db, c.id)
    assert res["request_payload"]["SOURCE_SYSTEM"] == "SIEGPU"  # 字面量注入


# ------------------------------ 分派 + 边界 ------------------------------

def test_sync_by_type_unknown_raises(db):
    with pytest.raises(ValueError):
        svc.sync_by_type(db, "bogus_type", uuid.uuid4())


def test_sync_by_type_not_found_returns_none(db):
    assert svc.sync_by_type(db, "customer", uuid.uuid4()) is None  # 实体不存在
    assert svc.sync_by_type(db, "customer", "not-a-uuid") is None  # 非 UUID


# ------------------------------ 重试 ------------------------------

def test_retry_log_resyncs_failed(db):
    """原 FAILED log 留审计；retry 按原实体重新出站 → 新 MOCK_SUCCESS log。"""
    c = master_service.create_entity(db, Customer, {"name": "重试客户"})
    # 手造一条 FAILED log（未真正同步过 → 无 SUCCESS log → retry 会新建）
    failed = EbsSyncLog(entity_type="customer", entity_id=str(c.id), entity_version="manualhash",
                        sync_type="create", status="FAILED", error_message="模拟失败")
    db.add(failed)
    db.flush()
    res = svc.retry_log(db, failed.id)
    assert res is not None
    assert res["status"] == "MOCK_SUCCESS"
    assert res["id"] != failed.id  # 新 log（旧 FAILED 留审计）
    assert res["skipped"] is False


def test_retry_log_not_found(db):
    assert svc.retry_log(db, uuid.uuid4()) is None
