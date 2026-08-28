"""金租流程服务（一期核心）。对应设计书 §4.4/§5.5。

- 建申请自动生成 9 标准节点；
- 节点按状态机推进；
- 放款：同事务写 capital_transaction(放款入金) + 生成 N 期还款计划，靠 plan_generated + 行锁幂等。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.acceptance import AcceptanceRecord
from app.models.capital import CapitalTransaction
from app.models.leasing import LeasingDisbursement, LeasingNode, LeasingProcess
from app.models.master import Supplier
from app.models.project import Project
from app.models.repayment import Repayment
from app.utils.repayment_plan import generate_plan

# 9 个标准节点（按序）
STANDARD_NODES = ["接触", "业务交流", "资料提交", "金租审核", "一次上会", "二次上会", "访谈", "批方案", "放款"]

# 节点状态机（合法迁移）
NODE_TRANSITIONS = {
    "未开始": {"进行中"},
    "进行中": {"已完成", "卡住"},
    "卡住": {"进行中"},
    "已完成": set(),
}


def create_process(db: Session, *, project_id, supplier_id, total_amount, annual_rate=None,
                   term_periods=None, payment_freq=None, repayment_method=None,
                   start_date=None, notes=None,
                   leasing_mode=None, financing_type=None, materials=None) -> LeasingProcess:
    proj = db.get(Project, project_id)
    if not proj or proj.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "供应商不存在", 404)
    if sup.type != "资金供应商":
        raise BusinessError("BAD_REQUEST", "供应商不是金租公司（type 必须为 资金供应商）", 400)

    proc = LeasingProcess(
        project_id=project_id, supplier_id=supplier_id, total_amount=total_amount,
        annual_rate=annual_rate, term_periods=term_periods, payment_freq=payment_freq,
        repayment_method=repayment_method, start_date=start_date, status="进行中", notes=notes,
        leasing_mode=leasing_mode, financing_type=financing_type, materials=materials,
    )
    db.add(proc)
    db.flush()
    for i, name in enumerate(STANDARD_NODES, 1):
        db.add(LeasingNode(process_id=proc.id, node_name=name, seq=i, status="未开始"))
    db.flush()
    return proc


def list_processes(db: Session, project_id=None):
    stmt = select(LeasingProcess).order_by(LeasingProcess.created_at.desc())
    if project_id:
        stmt = stmt.where(LeasingProcess.project_id == project_id)
    return db.execute(stmt).scalars().all()


# S12（缺陷#10）：金租申请编辑 / 作废

_EDITABLE_FIELDS = ("total_amount", "annual_rate", "term_periods", "payment_freq",
                    "repayment_method", "start_date", "notes", "leasing_mode", "financing_type")


def update_process(db: Session, *, process_id, operator_id=None, **fields) -> LeasingProcess:
    """缺陷#10：编辑金租申请（仅「进行中」且未放款可改；金额/利率/期数/频率/方式等）。"""
    proc = db.get(LeasingProcess, process_id)
    if not proc or proc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "金租申请不存在", 404)
    if proc.status != "进行中":
        raise BusinessError("STATE_ERROR", f"当前状态 {proc.status} 不允许修改（仅进行中且未放款可改）", 409)
    if proc.plan_generated:
        raise BusinessError("STATE_ERROR", "已放款并生成还款计划，不允许修改", 409)
    for k, v in fields.items():
        if k not in _EDITABLE_FIELDS:
            raise BusinessError("VALIDATION_ERROR", f"字段 {k} 不可编辑", 422)
        setattr(proc, k, v)
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="leasing_process",
               target_id=proc.id, after_json={k: str(getattr(proc, k, None)) for k in fields})
    return proc


def void_process(db: Session, *, process_id, operator_id=None) -> LeasingProcess:
    """缺陷#10：作废金租申请（仅未放款可作废，状态置「已作废」，节点冻结）。"""
    proc = db.get(LeasingProcess, process_id)
    if not proc or proc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "金租申请不存在", 404)
    if proc.plan_generated or proc.status == "已放款":
        raise BusinessError("STATE_ERROR", "已放款的申请不可作废", 409)
    if proc.status == "已作废":
        raise BusinessError("DUPLICATE", "该申请已作废", 409)
    proc.status = "已作废"
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="UPDATE", target_type="leasing_process",
               target_id=proc.id, after_json={"status": "已作废"})
    return proc


def get_process(db: Session, process_id):
    proc = db.get(LeasingProcess, process_id)
    if not proc or proc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "金租申请不存在", 404)
    nodes = db.execute(
        select(LeasingNode).where(LeasingNode.process_id == process_id).order_by(LeasingNode.seq)
    ).scalars().all()
    # 加载关联的项目和供应商名称
    proj = db.get(Project, proc.project_id)
    sup = db.get(Supplier, proc.supplier_id)
    return proc, nodes, proj, sup


def advance_node(db: Session, *, node_id, status, actual_date=None, stuck_reason=None) -> LeasingNode:
    node = db.get(LeasingNode, node_id)
    if not node or node.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "节点不存在", 404)
    allowed = NODE_TRANSITIONS.get(node.status, set())
    if status not in allowed:
        raise BusinessError("ILLEGAL_TRANSITION", f"节点不允许 {node.status} → {status}", 409)
    node.status = status
    if status == "已完成" and actual_date:
        node.actual_date = actual_date
    if status == "卡住" and stuck_reason:
        node.stuck_reason = stuck_reason
    # 取消卡住时清空原因
    if status == "进行中" and node.stuck_reason is not None:
        node.stuck_reason = None
    db.flush()
    return node


def disburse(db: Session, *, process_id, actual_disbursement_amount: Decimal,
             disbursement_date: date, disbursed_by, note: str | None = None):
    """放款：同事务生成放款入金流水 + N 期还款计划。幂等：plan_generated + SELECT FOR UPDATE。"""
    proc = db.execute(
        select(LeasingProcess).where(LeasingProcess.id == process_id).with_for_update()
    ).scalar_one_or_none()
    if not proc:
        raise BusinessError("NOT_FOUND", "金租申请不存在", 404)
    if proc.plan_generated or proc.status == "已放款":
        raise BusinessError("DUPLICATE", "已放款/已生成还款计划", 409)
    if proc.status not in ("进行中", "已批"):
        raise BusinessError("ILLEGAL_TRANSITION", f"不允许 {proc.status} → 已放款", 409)
    if not (proc.annual_rate is not None and proc.term_periods and proc.payment_freq and proc.repayment_method):
        raise BusinessError("BAD_REQUEST", "缺少 利率/期数/频率/方式，无法生成还款计划", 422)

    # 1) 放款入金（NF1 幂等键；四期 W4：入金租池 pool=LEASING）
    txn = CapitalTransaction(
        project_id=proc.project_id, source_type="金租融资", direction="IN",
        amount=actual_disbursement_amount, transaction_date=disbursement_date,
        leasing_process_id=proc.id, category="放款", idempotency_key=f"disburse:{proc.id}",
        note=note, created_by=disbursed_by, pool="LEASING",
    )
    db.add(txn)

    # 1.5) 资金置换：扫描项目中未置换的流贷/自有付款自动归还（v3.1）
    from app.services import audit_service as _audit
    from app.services import funding_service as fs
    replacements = fs.execute_replacement(
        db, project_id=proc.project_id, leasing_process_id=proc.id,
        disbursement_amount=actual_disbursement_amount,
        disbursement_date=disbursement_date, created_by=disbursed_by,
    )
    for fr in replacements:
        _audit.log(db, user_id=disbursed_by, action="SUPERSEDE", target_type="funding_replacement",
                   target_id=fr.id, after_json={"amount": str(fr.amount), "source": fr.source_type_replaced})

    # 2) 生成还款计划（复用 utils/repayment_plan）
    rows = generate_plan(
        principal=actual_disbursement_amount, annual_rate=proc.annual_rate,
        term_periods=proc.term_periods, payment_freq=proc.payment_freq,
        method=proc.repayment_method, disbursement_date=disbursement_date,
    )
    for r in rows:
        db.add(Repayment(
            leasing_process_id=proc.id, period=r.period, due_date=r.due_date,
            planned_principal=r.planned_principal, planned_interest=r.planned_interest, status="待还",
        ))

    # 3) 更新申请
    proc.actual_disbursement_amount = actual_disbursement_amount
    proc.disbursement_date = disbursement_date
    proc.status = "已放款"
    proc.plan_generated = True
    db.flush()
    _audit.log(db, user_id=disbursed_by, action="DISBURSE", target_type="leasing_process",
               target_id=proc.id, after_json={"amount": str(actual_disbursement_amount), "periods": len(rows)})
    return proc, txn, len(rows)


def add_disbursement(db: Session, *, process_id, acceptance_id, amount: Decimal, disbursement_date: date,
                     mode: str = "入池", replacement_date: date | None = None,
                     note: str | None = None, created_by=None) -> tuple:
    """新增一笔放款：校验所选采购验收（已通过、属本项目）→ 写放款记录 → 生成该笔还款计划 → 记账 → 置换。

    一次金租批准可多笔放款，每笔关联具体一批采购验收（验收→订单→合同→项目血缘），每笔独立生成还款计划。
    S8（缺陷#12/#13）：
    - mode=入池（默认）：金租融资 IN 入金租池（现状）
    - mode=直付：负债入账 IN + 供应商付款 OUT 两笔（金租代付，无现金进池，LEASING 池恒 0）；
      contract_id 取数（K5）：验收类型=采购验收时取验收订单的采购合同，销售验收 → NULL
    - replacement_date：置换归还日（缺省=放款日，金租置换流贷/自有垫资的真实归还日期）
    """
    proc = db.get(LeasingProcess, process_id)
    if not proc or proc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "金租申请不存在", 404)
    if proc.status not in ("进行中", "已批", "已放款"):
        raise BusinessError("ILLEGAL_TRANSITION", f"不允许 {proc.status} → 放款", 409)
    if not (proc.annual_rate is not None and proc.term_periods and proc.payment_freq and proc.repayment_method):
        raise BusinessError("BAD_REQUEST", "缺少 利率/期数/频率/方式，无法生成还款计划", 422)
    acc = db.get(AcceptanceRecord, acceptance_id)
    if not acc or acc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "验收记录不存在", 404)
    # 四期 W4 期3：放款依据放宽为「已通过的采购验收 或 销售验收」（硬流转 #5）
    if acc.acceptance_type not in ("采购验收", "销售验收") or acc.status != "已通过":
        raise BusinessError("PRECONDITION", "放款依据必须是已通过的采购验收或销售验收", 409)
    if acc.project_id != proc.project_id:
        raise BusinessError("PRECONDITION", "该验收不属于本项目", 409)
    if mode not in ("入池", "直付"):
        raise BusinessError("BAD_REQUEST", f"非法放款模式: {mode}", 422)
    replace_date = replacement_date or disbursement_date

    d = LeasingDisbursement(process_id=process_id, acceptance_id=acceptance_id, amount=amount,
                            disbursement_date=disbursement_date, mode=mode,
                            replacement_date=replace_date, note=note, created_by=created_by)
    db.add(d)
    db.flush()

    rows = generate_plan(principal=amount, annual_rate=proc.annual_rate,
                         term_periods=proc.term_periods, payment_freq=proc.payment_freq,
                         method=proc.repayment_method, disbursement_date=disbursement_date)
    for r in rows:
        db.add(Repayment(leasing_process_id=proc.id, disbursement_id=d.id, period=r.period,
                         due_date=r.due_date, planned_principal=r.planned_principal,
                         planned_interest=r.planned_interest, status="待还"))

    # 放款记账（S8）：入池=金租融资 IN；直付=负债入账 IN + 供应商付款 OUT（K5 取数）
    primary_in = None
    if mode == "直付":
        # K5：验收→订单→合同（采购验收才有采购合同；销售验收无）
        purchase_contract_id = None
        if acc.acceptance_type == "采购验收" and acc.order_id:
            from app.models.delivery import Order
            o = db.get(Order, acc.order_id)
            purchase_contract_id = o.contract_id if o else None
        primary_in = CapitalTransaction(
            project_id=proc.project_id, source_type="金租融资", direction="IN",
            amount=amount, transaction_date=disbursement_date,
            leasing_process_id=proc.id, category="直付融资入账", contract_id=purchase_contract_id,
            idempotency_key=f"disburse:{d.id}:liab", note=note or "金租直付：负债入账",
            created_by=created_by, pool="LEASING")
        db.add(primary_in)
        db.add(CapitalTransaction(
            project_id=proc.project_id, source_type="金租融资", direction="OUT",
            amount=amount, transaction_date=disbursement_date,
            leasing_process_id=proc.id, category="金租直付货款", contract_id=purchase_contract_id,
            idempotency_key=f"disburse:{d.id}:pay", note=note or "金租直付：代付供应商货款",
            created_by=created_by, pool="LEASING"))
    else:
        primary_in = CapitalTransaction(
            project_id=proc.project_id, source_type="金租融资", direction="IN",
            amount=amount, transaction_date=disbursement_date,
            leasing_process_id=proc.id, category="放款",
            idempotency_key=f"disburse:{d.id}", note=note, created_by=created_by,
            pool="LEASING")
        db.add(primary_in)

    from app.services import funding_service as fs
    fs.execute_replacement(db, project_id=proc.project_id, leasing_process_id=proc.id,
                           disbursement_amount=amount, disbursement_date=disbursement_date,
                           replacement_date=replace_date, created_by=created_by)

    if proc.status != "已放款":
        proc.status = "已放款"

    from app.services import audit_service as _audit
    _audit.log(db, user_id=created_by, action="DISBURSE", target_type="leasing_disbursement",
               target_id=d.id, after_json={"amount": str(amount), "periods": len(rows), "mode": mode})
    return d, primary_in, len(rows)


def list_disbursements(db: Session, process_id):
    return db.execute(select(LeasingDisbursement).where(
        LeasingDisbursement.process_id == process_id,
        LeasingDisbursement.deleted_at.is_(None),
    ).order_by(LeasingDisbursement.created_at)).scalars().all()
