"""端到端模拟数据（按真实测算表《七号项目测算表（商机5090）V5》生成）。

商机5090 = 1372 台 5090 算力服务器，金租直融模式。
业务节奏（按真实）：4月采购/金租放款 → 4-6月交付 → 6月末交货完毕 → 7/1点亮上线 → 7月起租。
客户 = TY科技(庭宇)；宽恒=设备商；远东=金租。
运行：docker compose exec backend python -m app.demo   幂等：项目 DEMO-5090 已存在则跳过。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.leasing import LeasingNode
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.project import Project
from app.models.repayment import Repayment
from app.models.user import User
from app.services import (
    billing_service as bill, capital_service as cap, contract_service as con,
    invoice_service as inv, leasing_service as leas, master_service as M,
    order_service as ord_svc, repayment_service as rep,
)

D = Decimal
DEMO_CODE = "DEMO-5090"

# —— 真实测算表参数 ——
QTY = 1372
UNIT_PRICE_EX = D("535398.23")          # 不含税单价 → 总额 ≈ 7.3457 亿
PURCHASE_AMOUNT_EX = D("734566371.68")  # 采购合同不含税
PURCHASE_INCL = D("830060000")          # 采购含税 = 金租本金
SALES_MONTHLY_INCL = D("21677600")      # 月销售含税 = 1372×15800
SALES_AMOUNT_EX = D("1227033962")       # 销售合同不含税总额(60月)
LEASE_PRINCIPAL = PURCHASE_INCL
LEASE_RATE = D("0.04")                  # 年化 4%


def _node_done(db, node_id, dt):
    leas.advance_node(db, node_id=node_id, status="进行中")
    leas.advance_node(db, node_id=node_id, status="已完成", actual_date=dt)


def run():
    db = SessionLocal()
    try:
        if db.execute(select(Project).where(Project.code == DEMO_CODE)).scalar_one_or_none():
            print(f"演示项目 {DEMO_CODE} 已存在，跳过（重跑请先 down -v 重置）。")
            return
        actor = db.execute(select(User).where(User.username == "cfo")).scalar_one().id

        print("【0】主数据（客户=TY科技；宽恒=设备商；远东=金租）")
        cust = M.create_entity(db, Customer, {"name": "TY科技(庭宇)", "industry": "智算中心", "contact_person": "TY 客户经理", "credit_rating": "AA"})
        eq = M.create_entity(db, EquipmentModel, {"name": "5090 算力服务器", "category": "大卡", "gpu_type": "5090", "gpu_count": 1, "memory": "32GB", "unit_price_reference": D("605000")})
        sup_dev = M.create_entity(db, Supplier, {"name": "宽恒设备", "type": "设备供应商", "contact_person": "李经理"})
        sup_lease = M.create_entity(db, Supplier, {"name": "远东金租", "type": "资金供应商", "contact_person": "赵客户经理"})
        bank = M.create_entity(db, Bank, {"name": "工商银行", "credit_line": D("100000000"), "annual_rate": D("0.0435")})
        db.commit()

        print("【1】项目 + 合同（采购13% / 销售6%，月租2167.76万，7/1起租 60月）")
        p = Project(name="商机5090(演示)", code=DEMO_CODE, total_investment=PURCHASE_INCL, start_date=date(2026, 4, 1))
        db.add(p); db.flush()
        sales = con.create_contract(db, project_id=p.id, type="SALES", party_id=cust.id, amount=SALES_AMOUNT_EX,
                                    tax_rate=D("0.06"), monthly_rent=SALES_MONTHLY_INCL,
                                    start_date=date(2026, 7, 1), end_date=date(2031, 6, 30), contract_no="S-5090")
        pur = con.create_contract(db, project_id=p.id, type="PURCHASE", party_id=sup_dev.id, amount=PURCHASE_AMOUNT_EX,
                                  tax_rate=D("0.13"), contract_no="P-5090", parent_contract_id=sales.id)
        db.commit()

        print("【2】金租申请(8.3006亿/4%/60月等额本息) + 推进9节点 + 放款 → 入金 + 60期还款")
        lp = leas.create_process(db, project_id=p.id, supplier_id=sup_lease.id, total_amount=LEASE_PRINCIPAL,
                                 annual_rate=LEASE_RATE, term_periods=60, payment_freq="月",
                                 repayment_method="等额本息", start_date=date(2026, 3, 1))
        nodes = db.execute(select(LeasingNode).where(LeasingNode.process_id == lp.id).order_by(LeasingNode.seq)).scalars().all()
        for n in nodes[:-1]:
            _node_done(db, n.id, date(2026, 3, 20))
        lp.status = "已批"; db.flush()
        leas.disburse(db, process_id=lp.id, actual_disbursement_amount=LEASE_PRINCIPAL,
                      disbursement_date=date(2026, 4, 10), disbursed_by=actor, note="金租直融：付采购款")
        _node_done(db, nodes[-1].id, date(2026, 4, 10))
        db.commit()

        print("【3】付设备款 8.3006 亿(含税) → 采购合同")
        cap.record_transaction(db, created_by=actor, project_id=p.id, source_type="金租融资", direction="OUT",
                               amount=PURCHASE_INCL, transaction_date=date(2026, 4, 12),
                               category="付设备款", note="付 1372 台 5090 采购款", contract_id=pur.id)
        db.commit()

        print("【4】订单 1372 台(4/1下单)，6月末交货完毕 → 7/1 点亮上线 → 资产(月折旧≈1101.85万)")
        o = ord_svc.create_order(db, project_id=p.id, equipment_model_id=eq.id, quantity=QTY,
                                 unit_price=UNIT_PRICE_EX, contract_id=pur.id, order_date=date(2026, 4, 1))
        ord_svc.light_on(db, order_id=o.id, actual_date=date(2026, 7, 1))  # 交货完毕后点亮上线
        db.commit()

        print("【5】计费 7 月（首月=7月整月，7/1 点亮起算）")
        bill.generate_billing(db, order_id=o.id, contract_id=sales.id, period_index=1,
                              billing_date=date(2026, 7, 31), created_by=actor)
        db.commit()

        print("【6】收 7 月租金")
        cap.record_transaction(db, created_by=actor, project_id=p.id, source_type="租金收入", direction="IN",
                               amount=SALES_MONTHLY_INCL, transaction_date=date(2026, 7, 10), category="租金", note="TY 7月租金")
        db.commit()

        print("【7】还金租：确认第1期(5/10到期，已还)，留第2/3期(6/10、7/10)逾期触发预警")
        reps = db.execute(select(Repayment).where(Repayment.leasing_process_id == lp.id).order_by(Repayment.period)).scalars().all()
        r1 = reps[0]
        amt1 = r1.planned_principal + r1.planned_interest
        rep.confirm_repayment(db, repayment_id=r1.id, actual_principal=r1.planned_principal,
                              actual_interest=r1.planned_interest, paid_date=date(2026, 5, 12))
        cap.record_transaction(db, created_by=actor, project_id=p.id, source_type="还款", direction="OUT",
                               amount=amt1, transaction_date=date(2026, 5, 12), category="还金租本息",
                               leasing_process_id=lp.id, note="第1期")
        db.commit()
        print(f"    月还 ≈ {amt1}（等额本息）；第2期到期 {reps[1].due_date}、第3期 {reps[2].due_date} 留待还")

        print("【8】发票 + 收付款 + 对账")
        inv_s = inv.create_invoice(db, contract_id=sales.id, amount=SALES_MONTHLY_INCL, invoice_no="SI-2026-07",
                                   issue_date=date(2026, 7, 5), due_date=date(2026, 8, 5))
        inv.mark_paid(db, inv_s.id, date(2026, 7, 10))
        inv_p = inv.create_invoice(db, contract_id=pur.id, amount=PURCHASE_INCL, invoice_no="PI-001",
                                   issue_date=date(2026, 4, 15), due_date=date(2026, 4, 30))
        inv.mark_paid(db, inv_p.id, date(2026, 4, 30))
        db.commit()

        print("\n===== 商机5090 模拟数据（真实测算表 + 6月交货/7月起租）写入完成 =====")
        s = cap.pool_summary(db)
        print(f"资金池余额: {s['pool_balance']}  | 入 {s['total_in']}  出 {s['total_out']}")
        print(f"  by_source net: { {k: v['net'] for k, v in s['by_source'].items()} }")
        recon = inv.reconciliation(db)
        if recon:
            r0 = recon[0]
            print(f"  销售对账: 合同 {r0['contract_amount']} | 应收 {r0['billed']} | 开票 {r0['invoiced']} | 收款 {r0['received']}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
