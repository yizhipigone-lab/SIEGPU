"""EBS 同步调度服务（二期 W1-2 骨架）。

核心职责：
1. 版本化 + 幂等：对实体业务字段算 sha256 短 hash 作 entity_version；同 entity_type+entity_id+
   entity_version 已有 SUCCESS/MOCK_SUCCESS 行 → 跳过（不新建 log、不再调 client）。
   版本只算业务字段（排除 id/created_at/updated_at/deleted_at），否则每次 save 时间戳变 → 永不幂等。
2. 字段映射：按 ebs_field_mappings 配置把 SIEGPU 字段重命名/转换成 EBS 字段（direct/constant 已实现；
   date_format/decimal_scale 期外）。无配置则原样出站（初期未配映射也能同步）。
3. 10 个标准出站方法（父计划 §3.1）：customer/supplier/contract/invoice/asset/payment/prepayment/
   lease_disbursement/repayment/goods_receipt。骨架期每个方法「加载实体→序列化→出站」，字段丰富度后续阶段补。
4. 日志：每次出站写一行 ebs_sync_logs（成功/失败都留）；失败可重试（按原实体重新出站，旧 log 留审计）。

调用方负责 commit（endpoint/scheduler），服务只 flush 拿 id。
"""
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.billing import Invoice
from app.models.capital import CapitalTransaction
from app.models.delivery import Order
from app.models.device import Device
from app.models.ebs import EbsFieldMapping, EbsSyncLog
from app.models.leasing import LeasingProcess
from app.models.master import Customer, Supplier
from app.models.project import Contract
from app.models.repayment import Repayment

from . import ebs_client

# 版本 hash 排除列：审计/时间戳列变化不应改 entity_version（否则永不幂等）。
_EXCLUDE_COLS = {"id", "created_at", "updated_at", "deleted_at"}

# entity_type → 业务模型（骨架映射；prepayment→Device 预付款字段、goods_receipt→Order 入库状态）。
# payment=资金收付(CapitalTransaction)、lease_disbursement=金租放款(LeasingProcess)。
_ENTITY_MODELS: dict[str, type] = {
    "customer": Customer,
    "supplier": Supplier,
    "contract": Contract,
    "invoice": Invoice,
    "asset": Asset,
    "payment": CapitalTransaction,
    "lease_disbursement": LeasingProcess,
    "repayment": Repayment,
    "prepayment": Device,
    "goods_receipt": Order,
}


# ------------------------------ 序列化与版本 ------------------------------

def _jsonable(v):
    """ORM 标量 → JSON 安全（Decimal→float，datetime/date→iso，UUID→str）。"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _entity_to_payload(obj) -> dict:
    """ORM 对象 → 业务字段 dict（排除审计/时间戳列，保证版本稳定）。None → {}。"""
    if obj is None:
        return {}
    return {
        c.key: _jsonable(getattr(obj, c.key))
        for c in sa_inspect(obj).mapper.column_attrs
        if c.key not in _EXCLUDE_COLS
    }


def _compute_version(payload: dict) -> str:
    """业务字段 → sha256 前 16 字符（规范化 JSON：sort_keys + ensure_ascii=False）。幂等/乱序判定用。"""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ------------------------------ 字段映射 ------------------------------

def _apply_mappings(db: Session, entity_type: str, payload: dict) -> dict:
    """按 ebs_field_mappings 把 SIEGPU 字段转成 EBS 字段。

    - direct：重命名为 ebs_field
    - constant：取 transform_config.value 作字面量
    - date_format / decimal_scale：期外实现，暂透传原字段
    - 无配置：原样返回（初期未配映射也能同步，便于联调）
    """
    rows = db.execute(
        select(EbsFieldMapping).where(EbsFieldMapping.entity_type == entity_type)
    ).scalars().all()
    if not rows:
        return dict(payload)
    by_siegpu = {r.siegpu_field: r for r in rows}
    out: dict = {}
    for k, v in payload.items():
        m = by_siegpu.get(k)
        if m is None:
            out[k] = v  # 未配置的字段原样保留
        elif m.transform_rule == "direct":
            out[m.ebs_field] = v
        elif m.transform_rule == "constant":
            out[m.ebs_field] = (m.transform_config or {}).get("value")
        else:  # date_format / decimal_scale 期外；暂透传并保留 siegpu 字段名
            out[k] = v
    return out


# ------------------------------ 日志序列化 ------------------------------

def log_to_dict(r: EbsSyncLog, skipped: bool = False) -> dict:
    return {
        "id": str(r.id),
        "entity_type": r.entity_type,
        "entity_id": r.entity_id,
        "entity_version": r.entity_version,
        "direction": r.direction,
        "sync_type": r.sync_type,
        "status": r.status,
        "ebs_reference": r.ebs_reference,
        "request_payload": r.request_payload,
        "response_payload": r.response_payload,
        "error_message": r.error_message,
        "retry_count": r.retry_count,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        "skipped": skipped,
    }


def _last_success(db: Session, entity_type: str, entity_id: str, entity_version: str) -> EbsSyncLog | None:
    """同实体同版本最近一条成功 log（幂等查重命中即跳过）。"""
    return db.execute(
        select(EbsSyncLog).where(
            EbsSyncLog.entity_type == entity_type,
            EbsSyncLog.entity_id == entity_id,
            EbsSyncLog.entity_version == entity_version,
            EbsSyncLog.status.in_(("SUCCESS", "MOCK_SUCCESS")),
        ).order_by(EbsSyncLog.synced_at.desc()).limit(1)
    ).scalars().first()


# ------------------------------ 核心出站 ------------------------------

def sync_entity(db: Session, entity_type: str, entity_id, payload: dict, sync_type: str = "create") -> dict:
    """核心出站：算版本 → 幂等查重 → 映射 → 调 client → 写日志。调用方负责 commit。

    幂等：同 entity_type+entity_id+entity_version 已成功 → 跳过，返回已有 log（skipped=True）。
    失败也留 log（status=FAILED），便于重试；成功覆盖为 MOCK_SUCCESS/SUCCESS 并记 ebs_reference。
    """
    entity_id = str(entity_id)
    version = _compute_version(payload)
    existing = _last_success(db, entity_type, entity_id, version)
    if existing is not None:
        return log_to_dict(existing, skipped=True)

    ebs_payload = _apply_mappings(db, entity_type, payload)
    log = EbsSyncLog(
        entity_type=entity_type, entity_id=entity_id, entity_version=version,
        direction="SIEGPU_TO_EBS", sync_type=sync_type, status="FAILED",
        request_payload=ebs_payload,
    )
    db.add(log)
    db.flush()  # 拿 id；不 commit（调用方控制事务）
    try:
        resp = ebs_client.post_entity(entity_type, ebs_payload, sync_type=sync_type)
        log.status = resp.get("status", "SUCCESS")  # Mock → MOCK_SUCCESS
        log.ebs_reference = resp.get("ebs_reference")
        log.response_payload = resp
    except Exception as exc:  # noqa: BLE001 —— 任何 client 异常都落 FAILED log，绝不向上冒泡拖垮调用方
        log.status = "FAILED"
        log.error_message = str(exc)[:500]
    log.synced_at = datetime.now(timezone.utc)
    return log_to_dict(log)


# ------------------------------ 10 个标准出站方法 ------------------------------

def _sync_model(db: Session, entity_type: str, entity_id, model: type, sync_type: str = "create") -> dict | None:
    """加载实体（走 select 触发软删除过滤）→ 序列化 → 出站。实体不存在返回 None。"""
    try:
        eid = uuid.UUID(str(entity_id))
    except (ValueError, AttributeError, TypeError):
        return None
    obj = db.execute(select(model).where(model.id == eid)).scalar_one_or_none()
    if obj is None:
        return None
    return sync_entity(db, entity_type, str(eid), _entity_to_payload(obj), sync_type=sync_type)


def sync_by_type(db: Session, entity_type: str, entity_id, sync_type: str = "create") -> dict | None:
    """按 entity_type 分派到对应模型。未知类型 → ValueError（端点转 400）。"""
    model = _ENTITY_MODELS.get(entity_type)
    if model is None:
        raise ValueError(f"未知 entity_type: {entity_type}（支持：{', '.join(_ENTITY_MODELS)}）")
    return _sync_model(db, entity_type, entity_id, model, sync_type=sync_type)


# 10 个具名方法（父计划 §3.1 显式列出；语义同 sync_by_type，保留具名便于业务侧直接调用/后续挂钩子）
def sync_customer(db: Session, customer_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "customer", customer_id, Customer, sync_type)


def sync_supplier(db: Session, supplier_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "supplier", supplier_id, Supplier, sync_type)


def sync_contract(db: Session, contract_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "contract", contract_id, Contract, sync_type)


def sync_invoice(db: Session, invoice_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "invoice", invoice_id, Invoice, sync_type)


def sync_asset(db: Session, asset_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "asset", asset_id, Asset, sync_type)


def sync_payment(db: Session, payment_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "payment", payment_id, CapitalTransaction, sync_type)


def sync_prepayment(db: Session, device_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "prepayment", device_id, Device, sync_type)


def sync_lease_disbursement(db: Session, process_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "lease_disbursement", process_id, LeasingProcess, sync_type)


def sync_repayment(db: Session, repayment_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "repayment", repayment_id, Repayment, sync_type)


def sync_goods_receipt(db: Session, order_id, sync_type: str = "create") -> dict | None:
    return _sync_model(db, "goods_receipt", order_id, Order, sync_type)


# ------------------------------ 重试 ------------------------------

def retry_log(db: Session, log_id) -> dict | None:
    """重试一条同步：按原实体重新出站。原 FAILED log 保留作审计，返回新 log。日志不存在 → None。"""
    log = db.execute(select(EbsSyncLog).where(EbsSyncLog.id == log_id)).scalar_one_or_none()
    if log is None:
        return None
    return sync_by_type(db, log.entity_type, log.entity_id, sync_type=log.sync_type)


# ------------------------------ 字段映射 CRUD + 日志查询 ------------------------------

def list_mappings(db: Session, entity_type: str | None = None) -> list[EbsFieldMapping]:
    q = select(EbsFieldMapping).order_by(EbsFieldMapping.entity_type, EbsFieldMapping.siegpu_field)
    if entity_type:
        q = q.where(EbsFieldMapping.entity_type == entity_type)
    return list(db.execute(q).scalars().all())


def create_mapping(db: Session, data: dict) -> EbsFieldMapping:
    """新建映射。同 entity_type+siegpu_field 已存在（活跃）→ ValueError（端点转 409）。"""
    exists = db.execute(
        select(EbsFieldMapping.id).where(
            EbsFieldMapping.entity_type == data["entity_type"],
            EbsFieldMapping.siegpu_field == data["siegpu_field"],
        )
    ).first()
    if exists is not None:
        raise ValueError(f"映射已存在：{data['entity_type']}.{data['siegpu_field']}")
    m = EbsFieldMapping(**data)
    db.add(m)
    db.flush()
    return m


def update_mapping(db: Session, mid, data: dict) -> EbsFieldMapping | None:
    m = db.execute(select(EbsFieldMapping).where(EbsFieldMapping.id == mid)).scalar_one_or_none()
    if m is None:
        return None
    for k, v in data.items():  # 仅更新传入字段（exclude_unset）
        if v is not None:
            setattr(m, k, v)
    db.flush()
    return m


def soft_delete_mapping(db: Session, mid) -> bool:
    from datetime import datetime as _dt
    res = db.execute(
        select(EbsFieldMapping).where(EbsFieldMapping.id == mid)
    ).scalar_one_or_none()
    if res is None:
        return False
    res.deleted_at = _dt.now(timezone.utc)
    db.flush()
    return True


def list_logs(db: Session, entity_type: str | None = None, status: str | None = None,
              limit: int = 100) -> list[EbsSyncLog]:
    q = select(EbsSyncLog).order_by(EbsSyncLog.synced_at.desc()).limit(limit)
    if entity_type:
        q = q.where(EbsSyncLog.entity_type == entity_type)
    if status:
        q = q.where(EbsSyncLog.status == status)
    return list(db.execute(q).scalars().all())
