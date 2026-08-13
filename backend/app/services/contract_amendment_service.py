"""合同变更/终止服务（二期 W9-10）。

变更：before/after 快照落 contract_amendments + 应用到合同（金额/月租/止日）+ audit + EBS Mock 出站。
联动说明：计费按周期现算（无预生成计划行），月租/税率变更落合同即对「未来期」计费自动生效
——联动测试据此断言（test_contract_amendment）。
终止：合同 status → 已终止 + contract_terminations 留痕 + EBS 出站。
service 不 commit 铁律：只 flush。
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.contract_ext import ContractAmendment, ContractTermination
from app.models.project import Contract
from app.services.contract_service import get_contract_or_404

# 变更可改字段（与 change_type 对应；其余字段走 PATCH 白名单，不算变更）
_AMENDABLE = ("amount", "monthly_rent", "end_date")


def create_amendment(db: Session, contract_id, *, change_type: str, amendment_date: date,
                     reason: str | None = None, new_amount: Decimal | None = None,
                     new_monthly_rent: Decimal | None = None, new_end_date: date | None = None,
                     actor_id: uuid.UUID | None = None) -> ContractAmendment:
    c = get_contract_or_404(db, contract_id)
    if c.status == "已终止":
        raise BusinessError("ILLEGAL_TRANSITION", "已终止合同不可变更", 409)
    if not reason or not reason.strip():
        raise BusinessError("BAD_REQUEST", "合同变更必须填写原因", 400)
    updates = {}
    if new_amount is not None:
        updates["amount"] = new_amount
    if new_monthly_rent is not None:
        updates["monthly_rent"] = new_monthly_rent
    if new_end_date is not None:
        updates["end_date"] = new_end_date
    if not updates:
        raise BusinessError("BAD_REQUEST", "变更内容为空（至少改一项：金额/月租/止日）", 400)

    before = {k: (str(getattr(c, k)) if getattr(c, k) is not None else None) for k in _AMENDABLE}
    for k, v in updates.items():
        setattr(c, k, v)
    after = {k: (str(getattr(c, k)) if getattr(c, k) is not None else None) for k in _AMENDABLE}
    row = ContractAmendment(contract_id=c.id, amendment_date=amendment_date, change_type=change_type,
                            before_json=before, after_json=after, reason=reason.strip(),
                            created_by=actor_id)
    db.add(row)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="contract",
               target_id=c.id, before_json=before, after_json=after)
    # EBS Mock 出站（内容变化 → 新版本 → 新 log；幂等机制兜底）
    from app.services import ebs_sync_service as _ebs
    try:
        _ebs.sync_contract(db, c.id, sync_type="update")
    except Exception:  # noqa: BLE001 —— EBS 旁路不阻断变更
        import logging
        logging.getLogger(__name__).warning("amendment: EBS sync failed for contract %s", c.id)
    return row


def list_amendments(db: Session, contract_id) -> list[ContractAmendment]:
    return list(db.execute(select(ContractAmendment).where(
        ContractAmendment.contract_id == contract_id
    ).order_by(ContractAmendment.amendment_date.desc())).scalars().all())


def terminate_contract(db: Session, contract_id, *, termination_date: date,
                       reason: str | None = None, settlement_note: str | None = None,
                       actor_id: uuid.UUID | None = None) -> ContractTermination:
    c = get_contract_or_404(db, contract_id)
    if c.status == "已终止":
        raise BusinessError("DUPLICATE", "合同已终止", 409)
    c.status = "已终止"
    # 三期 §4.4 合同终止结算：销售终止 → 资源释放（设备摘下销售合同，回退为可租/可用）
    released = 0
    if c.type == "SALES":
        from app.models.device import Device
        for d in db.execute(select(Device).where(
                Device.sales_contract_id == c.id, Device.deleted_at.is_(None))).scalars().all():
            d.sales_contract_id = None
            released += 1
        db.flush()
    row = ContractTermination(contract_id=c.id, termination_date=termination_date,
                              reason=reason, settlement_note=settlement_note,
                              created_by=actor_id)
    db.add(row)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=actor_id, action="UPDATE", target_type="contract",
               target_id=c.id, after_json={"status": "已终止", "reason": reason, "released_devices": released})
    from app.services import ebs_sync_service as _ebs
    try:
        _ebs.sync_contract(db, c.id, sync_type="update")
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("termination: EBS sync failed for contract %s", c.id)
    return row


def list_terminations(db: Session, contract_id) -> list[ContractTermination]:
    return list(db.execute(select(ContractTermination).where(
        ContractTermination.contract_id == contract_id
    ).order_by(ContractTermination.termination_date.desc())).scalars().all())


# ------------------------------ 金租规则参数（键值） ------------------------------

from app.models.contract_ext import LeasingRuleConfig  # noqa: E402


def list_leasing_rules(db: Session) -> list[LeasingRuleConfig]:
    return list(db.execute(select(LeasingRuleConfig).order_by(LeasingRuleConfig.rule_key)).scalars().all())


def set_leasing_rule(db: Session, *, rule_key: str, rule_value: str, description=None) -> LeasingRuleConfig:
    """upsert：同 key 覆盖 value（规则调参主场景）。"""
    r = db.execute(select(LeasingRuleConfig).where(
        LeasingRuleConfig.rule_key == rule_key)).scalar_one_or_none()
    if r is None:
        r = LeasingRuleConfig(rule_key=rule_key, rule_value=rule_value, description=description)
        db.add(r)
    else:
        r.rule_value = rule_value
        if description is not None:
            r.description = description
    db.flush()
    return r


def get_leasing_rule(db: Session, rule_key: str, default: str | None = None) -> str | None:
    r = db.execute(select(LeasingRuleConfig.rule_value).where(
        LeasingRuleConfig.rule_key == rule_key)).first()
    return r[0] if r else default
