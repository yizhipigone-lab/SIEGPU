"""保险管理服务（二期 W7-8）：保单 CRUD + 自动投保 + 价值占比分摊 + 归集/摊销 + 理赔。

核心规则：
- 保费 = q2(保额 × 费率)；分摊按设备 purchase_value 占比逐台 q2，**末台吃尾差**保合计精确（D6 同源量纲纪律）。
- 硬约束（折旧污染防线）：保费仅「点亮前窗口」（已转固未运营）可归集进资产原值；
  点亮后（运营中）一律长期待摊，进原值直接被拒。collected_at 置位后不可重复归集（幂等）。
- 自动投保（advisory）：设备进「在途」→ 批次运输险；「点亮验收」完成 → 单台财产险。
  无 insurance_configs 配置 → 不动作（零回归）；失败只记日志不阻塞设备推进（钩子在 device_service try/except 内）。
- 摊销：长期待摊按 amortization_months 逐月摊，amortization_schedule 产出计划项（本阶段不落执行）。

service 不 commit 铁律：本模块只 flush，commit 在 endpoint。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.device import BatchDevice, Device
from app.models.insurance import InsuranceConfig, InsurancePolicy, InsurancePolicyDevice
from app.utils.reconcile import q2

POLICY_TYPES = ("运输险", "财产险")


# ------------------------------ 纯函数：分摊与摊销 ------------------------------

def allocate_by_value(items: list[tuple[uuid.UUID, Decimal]], total: Decimal) -> list[tuple[uuid.UUID, Decimal]]:
    """按价值占比把 total 分摊到各台：逐台 q2，末台 = total − 前面合计（尾差兜底，Σ精确等于 total）。
    价值全 0/None → 均分（同样末台吃尾差）。
    """
    n = len(items)
    if n == 0:
        return []
    values = [v if v is not None else Decimal(0) for _, v in items]
    total_value = sum(values, Decimal(0))
    out: list[tuple[uuid.UUID, Decimal]] = []
    acc = Decimal(0)
    for i, (key, v) in enumerate(items):
        if i == n - 1:
            share = total - acc  # 末台吃尾差
        elif total_value > 0:
            share = q2(total * values[i] / total_value)
        else:
            share = q2(total / n)  # 无价值信息 → 均分
        out.append((key, share))
        acc += share
    return out


def amortization_schedule(premium: Decimal, months: int) -> list[dict]:
    """长期待摊逐月摊销计划：月摊 = q2(保费/月数)，末月吃尾差。返回 [{period, amount}, ...]。"""
    if months <= 0:
        raise BusinessError("BAD_REQUEST", "摊销月数必须 > 0", 400)
    monthly = q2(premium / months)
    rows = [{"period": i, "amount": monthly} for i in range(1, months + 1)]
    rows[-1]["amount"] = premium - monthly * (months - 1)  # 末月尾差
    return rows


# ------------------------------ 配置 ------------------------------

def list_configs(db: Session) -> list[InsuranceConfig]:
    return list(db.execute(select(InsuranceConfig).order_by(InsuranceConfig.policy_type)).scalars().all())


def create_config(db: Session, *, policy_type: str, default_rate=None, insured_ratio=None,
                  insurer_id=None, cost_allocation=None, active: bool = True) -> InsuranceConfig:
    if policy_type not in POLICY_TYPES:
        raise BusinessError("BAD_REQUEST", f"未知险种：{policy_type}", 400)
    exists = db.execute(select(InsuranceConfig.id).where(
        InsuranceConfig.policy_type == policy_type)).first()
    if exists is not None:
        raise BusinessError("DUPLICATE", f"险种 {policy_type} 的配置已存在", 409)
    c = InsuranceConfig(policy_type=policy_type, default_rate=default_rate, insured_ratio=insured_ratio,
                        insurer_id=insurer_id, cost_allocation=cost_allocation, active=active)
    db.add(c)
    db.flush()
    return c


def _active_config(db: Session, policy_type: str) -> InsuranceConfig | None:
    return db.execute(select(InsuranceConfig).where(
        InsuranceConfig.policy_type == policy_type, InsuranceConfig.active.is_(True))
    ).scalar_one_or_none()


# ------------------------------ 保单 CRUD + 分摊 ------------------------------

def list_policies(db: Session, project_id=None, policy_type=None, status=None) -> list[InsurancePolicy]:
    stmt = select(InsurancePolicy).order_by(InsurancePolicy.created_at.desc())
    if project_id:
        stmt = stmt.where(InsurancePolicy.project_id == project_id)
    if policy_type:
        stmt = stmt.where(InsurancePolicy.policy_type == policy_type)
    if status:
        stmt = stmt.where(InsurancePolicy.status == status)
    return list(db.execute(stmt).scalars().all())


def get_policy_or_404(db: Session, pid) -> InsurancePolicy:
    p = db.get(InsurancePolicy, pid)
    if not p or p.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "保单不存在", 404)
    return p


def list_policy_devices(db: Session, policy_id) -> list[InsurancePolicyDevice]:
    return list(db.execute(select(InsurancePolicyDevice).where(
        InsurancePolicyDevice.policy_id == policy_id)).scalars().all())


def _create_policy_with_devices(db: Session, *, project_id, policy_type: str, devices: list[Device],
                                insurer_id=None, insured_amount=None, premium_rate=None,
                                start_date=None, end_date=None, cost_allocation=None,
                                amortization_months=None, policy_no=None, batch_id=None,
                                trigger_event="手工", actor_id=None) -> InsurancePolicy:
    if policy_type not in POLICY_TYPES:
        raise BusinessError("BAD_REQUEST", f"未知险种：{policy_type}", 400)
    premium = q2(insured_amount * premium_rate) if (insured_amount is not None and premium_rate is not None) else None
    p = InsurancePolicy(
        project_id=project_id, batch_id=batch_id, policy_type=policy_type, policy_no=policy_no,
        insurer_id=insurer_id, insured_amount=insured_amount, premium_rate=premium_rate,
        premium_amount=premium, start_date=start_date, end_date=end_date,
        cost_allocation=cost_allocation, amortization_months=amortization_months,
        trigger_event=trigger_event, status="待确认",
    )
    db.add(p)
    db.flush()
    if premium is not None and devices:
        for dev_id, share in allocate_by_value([(d.id, d.purchase_value) for d in devices], premium):
            db.add(InsurancePolicyDevice(policy_id=p.id, device_id=dev_id, allocated_amount=share))
    else:  # 无保费也要落分摊行（金额 0），保证设备覆盖关系可查
        for d in devices:
            db.add(InsurancePolicyDevice(policy_id=p.id, device_id=d.id, allocated_amount=Decimal(0)))
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="CREATE", target_type="insurance_policy",
               target_id=p.id, after_json={"policy_type": policy_type, "premium": str(premium),
                                           "devices": len(devices), "trigger": trigger_event})
    return p


def create_policy(db: Session, *, project_id, policy_type: str, device_ids: list,
                  actor_id=None, **kw) -> InsurancePolicy:
    """手工录保单（端点用）。device_ids 必填（设备粒度是 W7-8 的核心）。"""
    if not device_ids:
        raise BusinessError("BAD_REQUEST", "保单必须覆盖至少一台设备", 400)
    devices = []
    for did in device_ids:
        d = db.get(Device, did)
        if not d or d.deleted_at is not None:
            raise BusinessError("NOT_FOUND", f"设备不存在：{did}", 404)
        devices.append(d)
    return _create_policy_with_devices(db, project_id=project_id, policy_type=policy_type,
                                       devices=devices, actor_id=actor_id, **kw)


def confirm_policy(db: Session, pid, actor_id=None) -> InsurancePolicy:
    p = get_policy_or_404(db, pid)
    if p.status != "待确认":
        raise BusinessError("ILLEGAL_TRANSITION", f"保单状态 {p.status} 不可确认（仅待确认可确认）", 409)
    p.status = "已生效"
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="insurance_policy",
               target_id=p.id, after_json={"status": "已生效"})
    return p


# ------------------------------ 归集（点亮前窗口硬约束） ------------------------------

def collect_to_asset(db: Session, pid, actor_id=None) -> InsurancePolicy:
    """保费按分摊额逐台归集进资产原值。硬约束：每台设备必须在「点亮前窗口」
    （资产卡存在且 operation_status='已转固未运营'）；任何一台已点亮（运营中）→ 整单拒绝
    （点亮后保费一律长期待摊，不触动折旧算法）。collected_at 幂等。"""
    p = get_policy_or_404(db, pid)
    if p.cost_allocation != "资产原值":
        raise BusinessError("BAD_REQUEST", "该保单归集口径不是「资产原值」", 400)
    if p.collected_at is not None:
        raise BusinessError("DUPLICATE", "保费已归集过，不可重复进原值", 409)
    rows = list_policy_devices(db, p.id)
    if not rows:
        raise BusinessError("BAD_REQUEST", "保单未覆盖设备，无分摊可归集", 400)
    # 先全量校验再动手（任一台不合规 → 整单拒，避免半归集）
    assets: list[tuple[Asset, Decimal]] = []
    for r in rows:
        a = db.execute(select(Asset).where(
            Asset.device_id == r.device_id, Asset.deleted_at.is_(None))).scalar_one_or_none()
        if a is None:
            d = db.get(Device, r.device_id)
            raise BusinessError("BAD_REQUEST",
                                f"设备 {d.sn if d else r.device_id} 未转固建卡（上架后才可归集原值）", 400)
        if a.operation_status != "已转固未运营":
            raise BusinessError("ILLEGAL_TRANSITION",
                                "设备已点亮（运营中）：点亮后保费一律走长期待摊，不得进资产原值（防折旧污染）", 409)
        assets.append((a, r.allocated_amount))
    for a, share in assets:
        a.unit_original_value += share
        a.total_original_value += share
    p.collected_at = datetime.now(timezone.utc)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="insurance_policy",
               target_id=p.id, after_json={"collected_at": str(p.collected_at),
                                           "total": str(sum((s for _, s in assets), Decimal(0)))})
    return p


def policy_amortization(db: Session, pid) -> list[dict]:
    """长期待摊摊销计划（本阶段只产出计划项，不落执行）。"""
    p = get_policy_or_404(db, pid)
    if p.cost_allocation != "长期待摊":
        raise BusinessError("BAD_REQUEST", "该保单归集口径不是「长期待摊」", 400)
    if p.premium_amount is None or p.amortization_months is None:
        raise BusinessError("BAD_REQUEST", "缺保费或摊销月数，无法生成摊销计划", 400)
    return amortization_schedule(p.premium_amount, p.amortization_months)


# ------------------------------ 理赔 ------------------------------

def register_claim(db: Session, pid, *, claim_date, amount: Decimal, description=None,
                   actor_id=None) -> InsurancePolicy:
    p = get_policy_or_404(db, pid)
    if p.status in ("已到期", "已退保"):
        raise BusinessError("ILLEGAL_TRANSITION", f"保单状态 {p.status} 不可登记理赔", 409)
    claims = list(p.claims or [])
    claims.append({"date": str(claim_date), "amount": str(amount),
                   "description": description, "by": str(actor_id) if actor_id else None})
    p.claims = claims
    p.status = "理赔中"
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="insurance_policy",
               target_id=p.id, after_json={"claim_amount": str(amount), "status": "理赔中"})
    return p


# ------------------------------ 自动投保（advisory hooks） ------------------------------

def maybe_auto_transport_policy(db: Session, *, batch_id, operator_id=None) -> InsurancePolicy | None:
    """批次设备进「在途」→ 按批次总价值 × insured_ratio 生成运输险（待确认）。幂等：每批次一张。"""
    cfg = _active_config(db, "运输险")
    if cfg is None or cfg.default_rate is None:
        return None
    existing = db.execute(select(InsurancePolicy).where(
        InsurancePolicy.batch_id == batch_id, InsurancePolicy.policy_type == "运输险")
    ).scalars().first()
    if existing is not None:
        return existing
    device_ids = db.execute(select(BatchDevice.device_id).where(
        BatchDevice.batch_id == batch_id, BatchDevice.active.is_(True))).scalars().all()
    devices = [d for d in (db.get(Device, did) for did in device_ids)
               if d is not None and d.deleted_at is None]
    devices = [d for d in devices if d.purchase_value is not None]
    if not devices:
        return None
    total_value = sum((d.purchase_value for d in devices), Decimal(0))
    if total_value <= 0:
        return None
    ratio = cfg.insured_ratio if cfg.insured_ratio is not None else Decimal(1)
    insured = q2(total_value * ratio)
    batch = devices[0]
    return _create_policy_with_devices(
        db, project_id=batch.project_id, policy_type="运输险", devices=devices,
        insurer_id=cfg.insurer_id, insured_amount=insured, premium_rate=cfg.default_rate,
        cost_allocation=cfg.cost_allocation, batch_id=batch_id, trigger_event="在途",
        actor_id=operator_id)


def maybe_auto_property_policy(db: Session, *, device: Device, operator_id=None) -> InsurancePolicy | None:
    """设备点亮验收完成 → 单台财产险（待确认）。幂等：每台设备一张。"""
    cfg = _active_config(db, "财产险")
    if cfg is None or cfg.default_rate is None or device.purchase_value is None:
        return None
    existing = db.execute(
        select(InsurancePolicyDevice).join(
            InsurancePolicy, InsurancePolicyDevice.policy_id == InsurancePolicy.id)
        .where(InsurancePolicyDevice.device_id == device.id,
               InsurancePolicy.policy_type == "财产险")
    ).scalars().first()
    if existing is not None:
        return None
    ratio = cfg.insured_ratio if cfg.insured_ratio is not None else Decimal(1)
    insured = q2(device.purchase_value * ratio)
    return _create_policy_with_devices(
        db, project_id=device.project_id, policy_type="财产险", devices=[device],
        insurer_id=cfg.insurer_id, insured_amount=insured, premium_rate=cfg.default_rate,
        cost_allocation=cfg.cost_allocation, trigger_event="点亮", actor_id=operator_id)
