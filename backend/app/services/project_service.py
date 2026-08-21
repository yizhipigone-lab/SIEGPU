from sqlalchemy.orm import Session

from app.models.project import Project


def create_project(
    db: Session,
    *,
    name: str,
    code: str | None = None,
    customer_id=None,
    total_investment=None,
    start_date=None,
    business_type=None,
    leasing_mode=None,
    parent_id=None,
    financing_plan=None,
) -> Project:
    p = Project(
        name=name,
        code=code,
        customer_id=customer_id,
        total_investment=total_investment,
        start_date=start_date,
        business_type=business_type,
        leasing_mode=leasing_mode,
        parent_id=parent_id,
        financing_plan=financing_plan,
    )
    db.add(p)
    db.flush()
    return p

def _f(v) -> float:
    """Decimal/None -> float（JSON 序列化；NULL 按 0）。"""
    return float(v) if v is not None else 0.0


def _prepayment_rollup(devices) -> dict:
    """采购订单级预付款汇总（devices 单一真源，D2）。

    状态口径：无预付款 / 已付挂账（未结转）/ 部分核销 / 已回核销。
    一期回租置位（prepayment_settled=True 且 settled_amount 为 NULL）按全额已结转计。
    """
    total = 0.0
    settled = 0.0
    for d in devices:
        amt = _f(d.prepayment_amount)
        if amt <= 0:
            continue
        total += amt
        if d.prepayment_settled_amount is not None:
            settled += _f(d.prepayment_settled_amount)
        elif d.prepayment_settled:  # 一期回租直接置位、无累计额的历史数据
            settled += amt
    remaining = round(total - settled, 2)
    if total <= 0:
        status = "无预付款"
    elif remaining <= 0:
        status = "已回核销"
    elif settled > 0:
        status = "部分核销"
    else:
        status = "已付挂账"
    return {"total": round(total, 2), "settled": round(settled, 2),
            "remaining": remaining, "status": status}


def project_relationships(db: Session, project_id) -> dict | None:
    """项目血缘树：合同（销售↔采购参照）/ 订单 / 预付款 / 金租申请 一次聚合。

    树形：项目 → 销售合同 →（销售订单；参照它的采购合同 → 采购订单 → 预付款 + 单台设备穿透）；
    项目 → 金租申请（leasing_processes.project_id 非空外键，模型层强制挂钩）。
    孤儿数据不丢：无参照的采购合同进 orphan_purchase_contracts，
    未挂合同的采购订单/批次进 unlinked_orders。
    """
    from sqlalchemy import select

    from app.models.billing import Invoice
    from app.models.delivery import Order
    from app.models.device import Device
    from app.models.leasing import LeasingProcess
    from app.models.master import Customer, Supplier
    from app.models.project import Contract
    from app.models.sales_order import SalesBatchDevice, SalesOrder
    from app.models.service_confirmation import ServiceConfirmation

    p = db.get(Project, project_id)
    if p is None:
        return None

    contracts = db.execute(
        select(Contract).where(Contract.project_id == project_id)
    ).scalars().all()
    sales_orders = db.execute(
        select(SalesOrder).where(SalesOrder.project_id == project_id)
    ).scalars().all()
    orders = db.execute(
        select(Order).where(Order.project_id == project_id)
    ).scalars().all()
    devices = db.execute(
        select(Device).where(Device.project_id == project_id)
    ).scalars().all()
    leasing = db.execute(
        select(LeasingProcess).where(LeasingProcess.project_id == project_id)
    ).scalars().all()

    # P1：发票（挂合同）与对账单（挂销售订单）——血缘树的资金/确认节点
    contract_ids = [c.id for c in contracts]
    invoices = db.execute(
        select(Invoice).where(Invoice.contract_id.in_(contract_ids))
    ).scalars().all() if contract_ids else []
    sales_order_ids = [so.id for so in sales_orders]
    confirmations = db.execute(
        select(ServiceConfirmation).where(ServiceConfirmation.sales_order_id.in_(sales_order_ids))
    ).scalars().all() if sales_order_ids else []

    # 往来单位名称（合同 party_type=supplier/customer 快照解析）
    party_ids = {c.party_id for c in contracts} | {lp.supplier_id for lp in leasing}
    sup = {s.id: s.name for s in db.execute(
        select(Supplier).where(Supplier.id.in_(party_ids))).scalars().all()} if party_ids else {}
    cus = {c.id: c.name for c in db.execute(
        select(Customer).where(Customer.id.in_(party_ids))).scalars().all()} if party_ids else {}

    def _party_name(c: Contract) -> str | None:
        return (sup.get(c.party_id) or cus.get(c.party_id)) if c.party_id else None

    # 设备按采购订单/批次归集（order_id 单台直挂；batch_id 批次挂载，二选一互斥由状态机保证）
    dev_by_order: dict = {}
    for d in devices:
        key = d.batch_id or d.order_id
        if key:
            dev_by_order.setdefault(key, []).append(d)

    # 销售批次已挂载设备数（批次汇总 + 单台穿透的汇总层）
    so_ids = [so.id for so in sales_orders]
    batch_dev_count: dict = {}
    if so_ids:
        for row in db.execute(
            select(SalesBatchDevice.sales_batch_id)
            .where(SalesBatchDevice.sales_batch_id.in_(so_ids), SalesBatchDevice.active.is_(True))
        ).all():
            batch_dev_count[row[0]] = batch_dev_count.get(row[0], 0) + 1

    def _device_node(d: Device) -> dict:
        settled_amt = d.prepayment_settled_amount
        if settled_amt is None and d.prepayment_settled:
            settled_amt = d.prepayment_amount
        return {
            "id": str(d.id), "sn": d.sn, "status": d.status,
            "prepayment_amount": _f(d.prepayment_amount),
            "prepayment_settled_amount": _f(settled_amt),
            "prepayment_settled": bool(d.prepayment_settled),
        }

    def _order_node(o: Order) -> dict:
        devs = dev_by_order.get(o.id, [])
        return {
            "id": str(o.id),
            "label": o.batch_name or (f"订单 {str(o.id)[:8]}"),
            "is_batch": bool(o.is_batch),
            "status": o.batch_status if o.is_batch else o.status,
            "quantity": o.quantity,
            "total_amount": _f(o.total_amount),
            "order_date": o.order_date.isoformat() if o.order_date else None,
            "prepayment": _prepayment_rollup(devs),
            "devices": [_device_node(d) for d in devs],
        }

    def _purchase_contract_node(c: Contract) -> dict:
        return {
            "id": str(c.id), "contract_no": c.contract_no,
            "amount": _f(c.amount), "amount_incl_tax": _f(c.amount_incl_tax),
            "status": c.status, "party_name": _party_name(c),
            "orders": [_order_node(o) for o in orders if o.contract_id == c.id],
        }

    linked_order_ids = {o.id for o in orders if o.contract_id is not None}

    sales_contracts = []
    for c in contracts:
        if c.type != "SALES":
            continue
        sales_contracts.append({
            "id": str(c.id), "contract_no": c.contract_no,
            "amount": _f(c.amount), "amount_incl_tax": _f(c.amount_incl_tax),
            "monthly_rent": _f(c.monthly_rent),
            "status": c.status, "party_name": _party_name(c),
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "sales_orders": [{
                "id": str(so.id),
                "label": so.batch_name or (f"订单 {str(so.id)[:8]}"),
                "is_batch": bool(so.is_batch),
                "status": so.batch_status if so.is_batch else so.status,
                "quantity": so.quantity,
                "total_monthly_rent": _f(so.total_monthly_rent),
                "device_count": batch_dev_count.get(so.id, 0),
                "confirmations": [{
                    "id": str(cf.id), "period_label": cf.period_label,
                    "status": cf.status,
                    "confirmed_at": cf.confirmed_at.isoformat() if cf.confirmed_at else None,
                } for cf in confirmations if cf.sales_order_id == so.id],
            } for so in sales_orders if so.contract_id == c.id],
            "invoices": [{
                "id": str(iv.id), "invoice_no": iv.invoice_no,
                "amount": _f(iv.amount), "amount_ex_tax": _f(iv.amount_ex_tax),
                "status": iv.status,
                "issue_date": iv.issue_date.isoformat() if iv.issue_date else None,
                "paid_date": iv.paid_date.isoformat() if iv.paid_date else None,
            } for iv in invoices if iv.contract_id == c.id and iv.direction == "RECEIVABLE"],
            "purchase_contracts": [
                _purchase_contract_node(pc) for pc in contracts
                if pc.type == "PURCHASE" and pc.parent_contract_id == c.id
            ],
        })

    return {
        "project": {"id": str(p.id), "name": p.name, "code": p.code, "status": p.status},
        "sales_contracts": sales_contracts,
        "orphan_purchase_contracts": [
            _purchase_contract_node(pc) for pc in contracts
            if pc.type == "PURCHASE" and pc.parent_contract_id is None
        ],
        "unlinked_orders": [_order_node(o) for o in orders if o.id not in linked_order_ids],
        "leasing_processes": [{
            "id": str(lp.id), "financing_type": lp.financing_type,
            "leasing_mode": lp.leasing_mode,
            "total_amount": _f(lp.total_amount),
            "actual_disbursement_amount": _f(lp.actual_disbursement_amount),
            "status": lp.status, "supplier_name": sup.get(lp.supplier_id),
            "start_date": lp.start_date.isoformat() if lp.start_date else None,
        } for lp in leasing],
    }
