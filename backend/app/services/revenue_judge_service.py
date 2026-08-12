"""收入核算路径判定服务（二期 W3-4）。

职责：判定（纯函数 rules）→ 快照写合同 → audit 留痕 → EBS Mock 出站（entity_type='contract_revenue_method'）。
只判定不驱动收入确认（D5：确认属三期 §4.2）。

触发点：
- 合同创建/更新（contract_service）自动判定：仅 SALES 且（项目已填 business_type 或合同已填任一判定输入）
  —— 无判定上下文的合同保持字段 NULL，旧流程零行为变化。
- 人工覆盖/确认（confirm_method）：必须填原因，记 method_confirmed_by/at + audit。
- 手动重判（端点 POST /contracts/{id}/judge）：无条件重判 SALES 合同。

service 不 commit 铁律：本模块只 flush，commit 在 endpoint。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.project import Contract, Project
from app.services import audit_service as audit
from app.services import ebs_sync_service
from app.utils import revenue_rules as rules
from app.utils.revenue_rules import JudgeResult


def _judge(db: Session, contract: Contract) -> JudgeResult:
    """对合同跑纯函数规则（输入：项目 business_type/leasing_mode + 合同三字段）。"""
    proj = db.get(Project, contract.project_id)
    return rules.judge_revenue_method(
        business_type=proj.business_type if proj else None,
        leasing_mode=proj.leasing_mode if proj else None,
        contract_type=contract.type,
        pricing_authority=contract.pricing_authority,
        inventory_risk_bearer=contract.inventory_risk_bearer,
        principal_role=contract.principal_role,
    )


def _sync_ebs(db: Session, contract: Contract, result: JudgeResult, confirmed: bool) -> None:
    """判定结果快照出站 EBS Mock（幂等：同内容同版本跳过）。绝不向上冒泡拖垮主流程。"""
    payload = {
        "contract_id": str(contract.id),
        "contract_no": contract.contract_no,
        "project_id": str(contract.project_id),
        "revenue_method": result.method,
        "judge_rule": result.rule,
        "method_judge_basis": result.basis,
        "method_confirmed": confirmed,
    }
    try:
        ebs_sync_service.sync_entity(db, "contract_revenue_method", contract.id, payload)
    except Exception:  # noqa: BLE001 —— EBS 是旁路出站，失败不落 log 也不阻断判定
        import logging
        logging.getLogger(__name__).warning("revenue_judge: EBS sync failed for contract %s", contract.id)


def should_auto_judge(db: Session, contract: Contract) -> bool:
    """自动判定门槛：SALES 且（项目有 business_type 或合同有任一判定输入）。否则保持 NULL 不动。"""
    if contract.type != "SALES":
        return False
    proj = db.get(Project, contract.project_id)
    if proj and proj.business_type:
        return True
    return any([contract.pricing_authority, contract.inventory_risk_bearer, contract.principal_role])


def judge_and_record(db: Session, contract: Contract, *, actor_id: uuid.UUID | None = None) -> JudgeResult:
    """系统判定并落合同快照 + audit + EBS 出站。PURCHASE 合同只返回结果不写库。"""
    result = _judge(db, contract)
    if result.method is None:
        return result
    contract.revenue_method = result.method
    contract.method_judge_basis = result.basis
    db.flush()
    audit.log(db, user_id=actor_id, action="REVENUE_JUDGE", target_type="contract",
              target_id=contract.id,
              after_json={"revenue_method": result.method, "rule": result.rule, "basis": result.basis})
    _sync_ebs(db, contract, result, confirmed=False)
    return result


def confirm_method(db: Session, contract: Contract, *, method: str, reason: str,
                   actor_id: uuid.UUID | None = None) -> Contract:
    """人工覆盖/确认核算路径。reason 必填（留痕动机）；记 confirmed_by/at + audit + EBS 出站。"""
    if method not in rules.METHODS:
        raise BusinessError("BAD_REQUEST", f"非法核算路径：{method}（可选：{'/'.join(rules.METHODS)}）", 400)
    if not reason or not reason.strip():
        raise BusinessError("BAD_REQUEST", "人工覆盖必须填写原因", 400)
    before = {"revenue_method": contract.revenue_method, "method_judge_basis": contract.method_judge_basis}
    contract.revenue_method = method
    contract.method_judge_basis = f"人工覆盖为「{method}」，原因：{reason.strip()}（原判定：{before['revenue_method'] or '无'}）"
    contract.method_confirmed_by = actor_id
    contract.method_confirmed_at = datetime.now(timezone.utc)
    db.flush()
    audit.log(db, user_id=actor_id, action="REVENUE_OVERRIDE", target_type="contract",
              target_id=contract.id, before_json=before,
              after_json={"revenue_method": method, "reason": reason.strip()})
    _sync_ebs(db, contract, JudgeResult(method, "MANUAL", contract.method_judge_basis), confirmed=True)
    return contract
