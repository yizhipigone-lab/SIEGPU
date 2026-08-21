"""对账中心服务（三期 §4.3）：1 维 → 7 维聚合 + 差异标记。

口径：金额默认不含税（与 customer_statement 自洽）；「已确认收入」= revenue_recognitions
状态 已确认/已同步EBS 的 Σamount（不含税）。差异标记 flags 为中文短句列表，前端标红渲染。
维度 6（业财一致性）Mock 局限：EBS Mock 两端口径天然一致，本期按父计划验收标准实现
`inject_demo=True` 手动注入 3 条模拟差异，验证展示/标红/定位管道（真对账属期外里程碑）。
"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import Billing, Invoice
from app.models.capital import CapitalTransaction
from app.models.device import Device
from app.models.delivery import Order
from app.models.asset import Asset
from app.models.master import Customer, Supplier
from app.models.payment import PaymentSettlement
from app.models.project import Contract, Project
from app.models.revenue import RevenueRecognition
from app.utils.reconcile import q2

RECOGNIZED_STATUSES = ("已确认", "已同步EBS")


def _sum(db, model_col, *conds) -> Decimal:
    return Decimal(db.execute(
        select(func.coalesce(func.sum(model_col), 0)).where(*conds)).scalar() or 0)


# ------------------------------ 维度 1：销售全链路 ------------------------------

def dim1_sales_chain(db: Session) -> list[dict]:
    """合同额 → 应收计费 → 已开票 → 已收款 → 已确认收入（每销售合同一行 + 差异标记）。"""
    rows = []
    for c in db.execute(select(Contract).where(Contract.type == "SALES")).scalars().all():
        billed = _sum(db, Billing.amount_ex_tax,
                      Billing.contract_id == c.id, Billing.status != "已红冲")
        invoiced = _sum(db, Invoice.amount_ex_tax,
                        Invoice.contract_id == c.id, Invoice.direction == "RECEIVABLE",
                        Invoice.status != "已红冲")
        received = _sum(db, Invoice.amount_ex_tax,
                        Invoice.contract_id == c.id, Invoice.direction == "RECEIVABLE",
                        Invoice.paid_date.isnot(None), Invoice.status != "已红冲")
        recognized = _sum(db, RevenueRecognition.amount,
                          RevenueRecognition.contract_id == c.id,
                          RevenueRecognition.status.in_(RECOGNIZED_STATUSES))
        flags = []
        if billed > invoiced:
            flags.append("已计未开")
        if invoiced > received:
            flags.append("已开未收")
        if received > invoiced:
            flags.append("已收未开")
        if recognized > invoiced:
            flags.append("已确认未开")
        if recognized > billed:
            flags.append("确认超计费")
        rows.append({
            "contract_id": str(c.id), "contract_no": c.contract_no or "—",
            "project_id": str(c.project_id),
            "contract_amount": q2(c.amount), "billed": q2(billed), "invoiced": q2(invoiced),
            "received": q2(received), "recognized": q2(recognized),
            "gap_unbilled": q2(c.amount - billed), "gap_uncollected": q2(invoiced - received),
            "flags": flags,
        })
    return rows


# ------------------------------ 维度 2：采购四单 ------------------------------

def dim2_purchase_chain(db: Session) -> list[dict]:
    """采购合同 → 采购发票 → 付款 + 预付款核销核对（每采购合同一行）。
    付款 = 旧 1:1 链接流水 + 新 payment_settlements 核销行（同 matched 口径，互斥不双计）。"""
    rows = []
    for c in db.execute(select(Contract).where(Contract.type == "PURCHASE")).scalars().all():
        invoiced = _sum(db, Invoice.amount,
                        Invoice.contract_id == c.id, Invoice.direction == "PAYABLE",
                        Invoice.status != "已红冲")
        inv_ids = list(db.execute(select(Invoice.id).where(
            Invoice.contract_id == c.id, Invoice.direction == "PAYABLE",
            Invoice.status != "已红冲")).scalars().all())
        paid_legacy = _sum(db, CapitalTransaction.amount,
                           CapitalTransaction.invoice_id.in_(inv_ids),
                           CapitalTransaction.deleted_at.is_(None)) if inv_ids else Decimal(0)
        paid_new = _sum(db, PaymentSettlement.amount,
                        PaymentSettlement.invoice_id.in_(inv_ids),
                        PaymentSettlement.deleted_at.is_(None)) if inv_ids else Decimal(0)
        paid = paid_legacy + paid_new
        # 预付款核销核对：项目设备预付款总额 / 已结转（冲抵视同结转）
        prepay_total = _sum(db, Device.prepayment_amount, Device.project_id == c.project_id)
        prepay_settled = _sum(db, Device.prepayment_settled_amount, Device.project_id == c.project_id)
        flags = []
        if paid > invoiced:
            flags.append("已付未开票")
        if invoiced > paid:
            flags.append("已开未付")
        if prepay_settled > prepay_total:
            flags.append("预付款核销超额")
        rows.append({
            "contract_id": str(c.id), "contract_no": c.contract_no or "—",
            "project_id": str(c.project_id),
            "contract_amount": q2(c.amount), "invoiced": q2(invoiced), "paid": q2(paid),
            "prepayment_total": q2(prepay_total), "prepayment_settled": q2(prepay_settled),
            "prepayment_remaining": q2(prepay_total - prepay_settled),
            "flags": flags,
        })
    return rows


# ------------------------------ 维度 3：资产交付 ------------------------------

_ARRIVED_STAGES = ("到货", "己方压测", "上架", "客户压测", "点亮验收")


def dim3_asset_delivery(db: Session) -> list[dict]:
    """采购数量 → 到货数量 → 转固数量 → 点亮数量（每项目一行，单台计数）。"""
    rows = []
    for p in db.execute(select(Project)).scalars().all():
        ordered = db.execute(select(func.coalesce(func.sum(Order.quantity), 0)).where(
            Order.project_id == p.id, Order.deleted_at.is_(None))).scalar() or 0
        devices = db.execute(select(Device).where(
            Device.project_id == p.id, Device.deleted_at.is_(None))).scalars().all()
        arrived = sum(1 for d in devices if d.status in _ARRIVED_STAGES)
        lit = sum(1 for d in devices if d.status == "点亮验收")
        capitalized = db.execute(select(func.count(Asset.id)).where(
            Asset.project_id == p.id, Asset.deleted_at.is_(None))).scalar() or 0
        flags = []
        if int(ordered) != len(devices):
            flags.append("采购≠入库台数")
        if capitalized != arrived:
            flags.append("转固≠到货")
        if lit > capitalized:
            flags.append("点亮超转固")
        rows.append({
            "project_id": str(p.id), "project_name": p.name,
            "ordered": int(ordered), "devices": len(devices), "arrived": arrived,
            "capitalized": int(capitalized), "lit": lit, "flags": flags,
        })
    return rows


# ------------------------------ 维度 4：监管账户 ------------------------------

def dim4_supervised_accounts(db: Session) -> list[dict]:
    """监管户合同：租金收入（已回款） vs 还款支出 vs 最低留存额（leasing_rule_configs
    `supervised_min_retention`，缺省 0=不校验）。"""
    from app.services.contract_amendment_service import get_leasing_rule
    min_retention = Decimal(get_leasing_rule(db, "supervised_min_retention", "0") or "0")
    rows = []
    for c in db.execute(select(Contract).where(
            Contract.type == "SALES", Contract.collection_account_type == "监管户")).scalars().all():
        received = _sum(db, Invoice.amount,
                        Invoice.contract_id == c.id, Invoice.direction == "RECEIVABLE",
                        Invoice.paid_date.isnot(None), Invoice.status != "已红冲")
        repaid = _sum(db, CapitalTransaction.amount,
                      CapitalTransaction.project_id == c.project_id,
                      CapitalTransaction.source_type == "还款",
                      CapitalTransaction.deleted_at.is_(None))
        balance = received - repaid
        flags = []
        if min_retention > 0 and balance < min_retention:
            flags.append("留存不足")
        rows.append({
            "contract_id": str(c.id), "contract_no": c.contract_no or "—",
            "project_id": str(c.project_id), "received": q2(received), "repaid": q2(repaid),
            "balance": q2(balance), "min_retention": q2(min_retention), "flags": flags,
        })
    return rows


# ------------------------------ 维度 5：汇兑损益核对 ------------------------------

def dim5_fx_check(db: Session) -> list[dict]:
    """汇兑损益入账核对：每条汇兑损益流水 vs 设备分摊行合计（分摊核对）；未分摊标注。"""
    rows = []
    for t in db.execute(select(CapitalTransaction).where(
            CapitalTransaction.category == "汇兑损益",
            CapitalTransaction.deleted_at.is_(None))).scalars().all():
        split = _sum(db, PaymentSettlement.amount,
                     PaymentSettlement.capital_transaction_id == t.id,
                     PaymentSettlement.deleted_at.is_(None))
        flags = []
        if split > 0 and split != t.amount:
            flags.append("分摊不平")
        if split == 0:
            flags.append("未分摊到设备")
        rows.append({
            "txn_id": str(t.id), "direction": t.direction, "amount": q2(t.amount),
            "transaction_date": t.transaction_date.isoformat(),
            "split_to_devices": q2(split), "note": t.note, "flags": flags,
        })
    return rows


# ------------------------------ 维度 6：业财一致性（Mock） ------------------------------

def dim6_ebs_consistency(db: Session, inject_demo: bool = False) -> list[dict]:
    """SIEGPU 业务数 vs EBS 财务数（Mock 镜像口径）。
    inject_demo=True：手动注入 3 条模拟差异（应收/资产/资金），验证展示-标红-定位管道
    （父计划 §4.3 维度 6 验收标准；真实对账属期外里程碑）。"""
    receivable = _sum(db, Invoice.amount_ex_tax,
                      Invoice.direction == "RECEIVABLE", Invoice.status != "已红冲") - \
                 _sum(db, Invoice.amount_ex_tax,
                      Invoice.direction == "RECEIVABLE", Invoice.paid_date.isnot(None),
                      Invoice.status != "已红冲")
    payable = _sum(db, Invoice.amount_ex_tax,
                   Invoice.direction == "PAYABLE", Invoice.status != "已红冲") - \
              _sum(db, Invoice.amount_ex_tax,
                   Invoice.direction == "PAYABLE", Invoice.paid_date.isnot(None),
                   Invoice.status != "已红冲")
    assets = _sum(db, Asset.total_original_value, Asset.deleted_at.is_(None))
    inn = _sum(db, CapitalTransaction.amount, CapitalTransaction.direction == "IN",
               CapitalTransaction.deleted_at.is_(None))
    out = _sum(db, CapitalTransaction.amount, CapitalTransaction.direction == "OUT",
               CapitalTransaction.deleted_at.is_(None))
    net = inn - out
    items = [
        {"item": "应收余额", "siegpu": q2(receivable), "ebs": q2(receivable)},
        {"item": "应付余额", "siegpu": q2(payable), "ebs": q2(payable)},
        {"item": "资产原值", "siegpu": q2(assets), "ebs": q2(assets)},
        {"item": "资金净头寸", "siegpu": q2(net), "ebs": q2(net)},
    ]
    if inject_demo:  # 注入 3 条模拟差异（应收 +1000 / 资产 −500 / 资金 +233.33）
        items[0]["ebs"] = q2(Decimal(items[0]["ebs"]) + Decimal("1000"))
        items[2]["ebs"] = q2(Decimal(items[2]["ebs"]) - Decimal("500"))
        items[3]["ebs"] = q2(Decimal(items[3]["ebs"]) + Decimal("233.33"))
    for it in items:
        it["diff"] = q2(Decimal(it["siegpu"]) - Decimal(it["ebs"]))
        it["flags"] = ["业财差异"] if it["diff"] != 0 else []
    return items


# ------------------------------ 维度 7：三流差异明细 ------------------------------

def dim7_flow_diffs(db: Session, customer_id=None, supplier_id=None) -> list[dict]:
    """全域三流差异明细（只列有差异的行）：销售侧 + 采购侧合并，按客户/供应商筛选。"""
    rows = []
    for r in dim1_sales_chain(db):
        c = db.get(Contract, r["contract_id"])
        if customer_id and str(c.party_id) != str(customer_id):
            continue
        if not r["flags"]:
            continue
        cust = db.get(Customer, c.party_id)
        rows.append({"side": "销售", "party_name": cust.name if cust else "—",
                     "contract_no": r["contract_no"], "flags": r["flags"],
                     "gap_unbilled": r["gap_unbilled"], "gap_uncollected": r["gap_uncollected"],
                     "paid": None, "invoiced": r["invoiced"]})
    for r in dim2_purchase_chain(db):
        c = db.get(Contract, r["contract_id"])
        if supplier_id and str(c.party_id) != str(supplier_id):
            continue
        if not r["flags"]:
            continue
        sup = db.get(Supplier, c.party_id)
        rows.append({"side": "采购", "party_name": sup.name if sup else "—",
                     "contract_no": r["contract_no"], "flags": r["flags"],
                     "gap_unbilled": None, "gap_uncollected": None,
                     "paid": r["paid"], "invoiced": r["invoiced"]})
    return rows

# ------------------------------ 维度 8：预付款双轨勾稽（四期 W4 期1 R1 既定后续） --------------

def dim8_prepay_parity(db: Session) -> list[dict]:
    """PREPAY 池余额（资金台账轨）vs Σ设备预付剩余（运营轨），按项目勾稽。

    计划书 R1：两套口径是同一笔钱——池只管资金进出（预付挂账/退回/核销），
    devices 逐台字段管运营/计费结转。本维度把两轨余额摆在一起，差异即漏记/错轨。
    只列任一轨非零的项目；|diff| > 0.01 → 「双轨差异」。
    """
    # 资金台账轨：PREPAY 池按项目 ΣIN−ΣOUT
    pool_rows = db.execute(
        select(CapitalTransaction.project_id, CapitalTransaction.direction,
               func.coalesce(func.sum(CapitalTransaction.amount), 0))
        .where(CapitalTransaction.pool == "PREPAY")
        .group_by(CapitalTransaction.project_id, CapitalTransaction.direction)
    ).all()
    pool_by_proj: dict = {}
    for pid, d, s in pool_rows:
        cur = pool_by_proj.get(pid, Decimal(0))
        pool_by_proj[pid] = cur + (Decimal(s) if d == "IN" else -Decimal(s))

    # 运营轨：设备预付剩余（未结清；一期回租置位 settled=True 剩余按 0）
    dev_by_proj: dict = {}
    for d in db.execute(select(Device).where(Device.prepayment_amount > 0)).scalars().all():
        if d.prepayment_settled:
            continue
        remaining = d.prepayment_amount - (d.prepayment_settled_amount or Decimal(0))
        if remaining > 0:
            dev_by_proj[d.project_id] = dev_by_proj.get(d.project_id, Decimal(0)) + remaining

    rows = []
    for pid in set(pool_by_proj) | set(dev_by_proj):
        pool_bal = pool_by_proj.get(pid, Decimal(0))
        dev_rem = dev_by_proj.get(pid, Decimal(0))
        if pool_bal == 0 and dev_rem == 0:
            continue
        diff = pool_bal - dev_rem
        proj = db.get(Project, pid)
        rows.append({
            "project_id": str(pid), "project_name": proj.name if proj else "—",
            "pool_balance": q2(pool_bal), "device_remaining": q2(dev_rem), "diff": q2(diff),
            "flags": ["双轨差异"] if abs(diff) > Decimal("0.01") else [],
        })
    return rows
