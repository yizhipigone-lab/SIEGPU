"""端到端全链路模拟数据（v3.1 18步完整流程）。

商机5090 = 1372 台 5090 算力服务器，金租直融模式。
真实业务节奏：银行流贷+自有资金垫付设备款 → 金租审批放款 → 置换归还。
客户=TY科技(庭宇)；宽恒=设备商；远东=金租；工商银行=流贷。
运行：docker compose exec backend python -m app.demo   幂等：DEMO-5090 已存在则跳过。
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
    acceptance_service as acc, billing_service as bill, capital_service as cap,
    confirmation_service as conf, contract_service as con, funding_service as fund,
    invoice_service as inv, leasing_service as leas, master_service as M,
    order_service as ord_svc, profit_service as profit,
    repayment_service as rep, sales_order_service as so_svc,
)

D = Decimal
DEMO_CODE = "DEMO-5090"

# —— 真实测算表参数 ——
QTY = 1372
UNIT_PRICE_EX = D("535398.23")           # 不含税单价
PURCHASE_AMOUNT_EX = D("734566371.68")   # 采购合同不含税 ≈ 7.35亿
PURCHASE_INCL = D("830060000")           # 采购含税 ≈ 8.30亿 = 金租本金
SALES_MONTHLY_INCL = D("21677600")       # 月销售含税 = 1372×15800
LEASE_PRINCIPAL = PURCHASE_INCL          # 金租融资本金
LEASE_RATE = D("0.04")                   # 年化 4%
LEASE_TERM = 60

# 融资结构：流贷70% + 自有30%
LOAN_RATIO = D("0.70")
EQUITY_RATIO = D("0.30")
LOAN_AMOUNT = (PURCHASE_INCL * LOAN_RATIO).quantize(D("0.01"))
EQUITY_AMOUNT = PURCHASE_INCL - LOAN_AMOUNT


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

        # ====== Step 1: 项目建立 ======
        print("【1】项目建立 — 商机5090")
        _ = Project(name="商机5090(全链路演示)", code=DEMO_CODE,
                    total_investment=PURCHASE_INCL, start_date=date(2026, 4, 1))
        db.add(_); db.flush()
        pid = _.id
        # v3.2: 创建向导式工作流
        from app.services import workflow_service as _wfsvc
        _wfsvc.create_workflow(db, project_id=pid)
        print(f"  项目 ID={pid}  总投资={PURCHASE_INCL}")

        # ====== Step 0: 主数据 ======
        print("【0】主数据（客户=TY科技；宽恒=设备商；远东=金租；工商银行=流贷）")
        cust = M.create_entity(db, Customer, {"name": "TY科技(庭宇)", "industry": "智算中心",
            "contact_person": "TY客户经理", "credit_rating": "AA"})
        eq = M.create_entity(db, EquipmentModel, {"name": "5090算力服务器", "category": "大卡",
            "gpu_type": "5090", "gpu_count": 1, "memory": "32GB", "unit_price_reference": D("605000")})
        sup_dev = M.create_entity(db, Supplier, {"name": "宽恒设备", "type": "设备供应商", "contact_person": "李经理"})
        sup_lease = M.create_entity(db, Supplier, {"name": "远东金租", "type": "资金供应商", "contact_person": "赵客户经理"})
        bank = M.create_entity(db, Bank, {"name": "工商银行", "credit_line": D("1000000000"),
            "annual_rate": D("0.0435")})
        db.commit()

        # ====== Step 2: 多子合同 ======
        print("【2】销售合同(parent) + 采购子合同(级联)")
        sales_contract = con.create_contract(db, project_id=pid, type="SALES", party_id=cust.id,
            amount=D("1227033962"), tax_rate=D("0.06"), monthly_rent=SALES_MONTHLY_INCL,
            start_date=date(2026, 7, 1), end_date=date(2031, 6, 30), contract_no="S-5090")
        purchase_contract = con.create_contract(db, project_id=pid, type="PURCHASE", party_id=sup_dev.id,
            amount=PURCHASE_AMOUNT_EX, tax_rate=D("0.13"), contract_no="P-5090",
            parent_contract_id=sales_contract.id)
        db.commit()
        print(f"  销售合同 {sales_contract.id}  采购合同 {purchase_contract.id}")

        # ====== Step 3: 销售订单 ======
        print("【3】销售订单 — 1372台5090，月租含税2167.76万")
        so = so_svc.create_sales_order(db, project_id=pid, contract_id=sales_contract.id,
            equipment_model_id=eq.id, quantity=QTY, monthly_rent_per_unit=D("15800"),
            total_monthly_rent=SALES_MONTHLY_INCL, start_date=date(2026, 7, 1),
            end_date=date(2031, 6, 30))
        db.commit()
        print(f"  销售订单 {so.id}")

        # ====== Step 4: 采购订单 ======
        print("【4】采购订单 — 1372台")
        po = ord_svc.create_order(db, project_id=pid, equipment_model_id=eq.id, quantity=QTY,
            unit_price=UNIT_PRICE_EX, contract_id=purchase_contract.id, order_date=date(2026, 4, 1))
        db.commit()
        print(f"  采购订单 {po.id}")

        # ====== Step 5: 银行流贷 IN ======
        print(f"【5】银行流贷 IN — {LOAN_AMOUNT}（70%）")
        cap.record_transaction(db, created_by=actor, project_id=pid, source_type="银行流贷",
            direction="IN", amount=LOAN_AMOUNT, transaction_date=date(2026, 4, 5),
            bank_id=bank.id, category="流贷", note="工商银行流贷，用于垫付设备款")
        db.commit()

        # ====== Step 6: 自有资金 IN ======
        print(f"【6】自有资金 IN — {EQUITY_AMOUNT}（30%）")
        cap.record_transaction(db, created_by=actor, project_id=pid, source_type="自有资金",
            direction="IN", amount=EQUITY_AMOUNT, transaction_date=date(2026, 4, 5),
            category="自有", note="自有资金垫付设备款")
        db.commit()

        # ====== Step 7: 预付采购款 OUT ======
        print(f"【7】预付采购款 — 流贷{LOAN_AMOUNT} + 自有{EQUITY_AMOUNT} → 付设备商")
        cap.record_transaction(db, created_by=actor, project_id=pid, source_type="银行流贷",
            direction="OUT", amount=LOAN_AMOUNT, transaction_date=date(2026, 4, 8),
            category="付设备款", note="流贷垫付：1372台5090采购款",
            contract_id=purchase_contract.id)
        cap.record_transaction(db, created_by=actor, project_id=pid, source_type="自有资金",
            direction="OUT", amount=EQUITY_AMOUNT, transaction_date=date(2026, 4, 8),
            category="付设备款", note="自有垫付：1372台5090采购款",
            contract_id=purchase_contract.id)
        db.commit()

        # ====== Step 8: 金租申请+9节点 ======
        print("【8】金租申请(8.3006亿/4%/60月等额本息) + 推进9节点")
        lp = leas.create_process(db, project_id=pid, supplier_id=sup_lease.id,
            total_amount=LEASE_PRINCIPAL, annual_rate=LEASE_RATE, term_periods=LEASE_TERM,
            payment_freq="月", repayment_method="等额本息", start_date=date(2026, 3, 1))
        nodes = db.execute(select(LeasingNode).where(LeasingNode.process_id == lp.id)
            .order_by(LeasingNode.seq)).scalars().all()
        for n in nodes[:-1]:  # 前8节点推进完成
            _node_done(db, n.id, date(2026, 3, 20))
        lp.status = "已批"
        db.commit()
        print(f"  金租申请 {lp.id}  节点数={len(nodes)}")

        # ====== Step 9: 金租放款 + 自动置换 ======
        print(f"【9】金租放款 {LEASE_PRINCIPAL} + 自动置换（归还流贷+自有）")
        proc, txn, n_repay = leas.disburse(db, process_id=lp.id,
            actual_disbursement_amount=LEASE_PRINCIPAL,
            disbursement_date=date(2026, 4, 10), disbursed_by=actor,
            note="金租直融：付采购款")

        # 查看置换结果
        replacements = fund.list_replacements(db, project_id=pid)
        total_replaced = sum(r.amount for r in replacements)
        print(f"  放款入金 {txn.amount}  还款计划 {n_repay}期  置换 {len(replacements)}笔 共{total_replaced}")
        for r in replacements:
            print(f"    → 置换 {r.source_type_replaced} {r.amount} (原始付款 {r.original_txn_id})")
        _node_done(db, nodes[-1].id, date(2026, 4, 10))
        db.commit()

        # ====== Step 10: 采购验收 ======
        print("【10】采购验收 — 1372台到货质检")
        ar_pur = acc.create_acceptance(db, project_id=pid, acceptance_type="采购验收",
            order_id=po.id, inspector="张质检员", quantity_accepted=QTY, quantity_rejected=0)
        acc.approve_acceptance(db, ar_pur, quantity_accepted=QTY,
            acceptance_date=date(2026, 5, 15))
        db.commit()
        print(f"  采购验收 {ar_pur.id} — 通过 {ar_pur.quantity_accepted}台")

        # ====== Step 11: 交付6阶段 ======
        print("【11】交付6阶段：订货→到货→压测→运输在途→上架→点亮(待点亮)")
        from app.models.delivery import DeliveryStage
        stages = db.execute(select(DeliveryStage).where(
            DeliveryStage.order_id == po.id).order_by(DeliveryStage.seq)).scalars().all()
        for s in stages[:-1]:  # 前5阶段
            s.status = "进行中"
            s.status = "已完成"
            s.actual_date = date(2026, 6, 20)
        db.commit()
        print(f"  交付阶段 {len(stages)}个，前5阶段已完成")

        # ====== Step 12: 销售验收 ======
        print("【12】销售验收 — 客户TY科技签收")
        ar_sales = acc.create_acceptance(db, project_id=pid, acceptance_type="销售验收",
            sales_order_id=so.id, inspector="TY客户代表", quantity_accepted=QTY, quantity_rejected=0)
        acc.approve_acceptance(db, ar_sales, quantity_accepted=QTY,
            acceptance_date=date(2026, 6, 28))
        db.commit()
        print(f"  销售验收 {ar_sales.id} — 通过 {ar_sales.quantity_accepted}台")

        # ====== Step 13: 点亮 + 资产生成 ======
        print("【13】点亮上线 → 同事务生成固定资产（月折旧≈1101.85万）")
        ord_svc.light_on(db, order_id=po.id, actual_date=date(2026, 7, 1))
        db.commit()
        print(f"  点亮日=2026-07-01  折旧起=2026-07-01  止=2031-06-30")

        # ====== Step 14: 计费（3个月） ======
        print("【14】计费：7月(首月整月) + 8月 + 9月")
        billings = []
        for i in range(1, 4):
            month = 6 + i
            b = bill.generate_billing(db, order_id=po.id, contract_id=sales_contract.id,
                period_index=i, billing_date=date(2026, month, 28 if month != 7 else 31),
                created_by=actor)
            billings.append(b)
        db.commit()
        for b in billings:
            print(f"  计费 period={b.period_index} {b.period_label} 含税={b.amount}")

        # ====== Step 15: 客户确认 ======
        print("【15】客户确认单 — 上传7月算力服务确认单")
        b1 = billings[0]
        sc = conf.create_confirmation(db, billing_id=b1.id, sales_order_id=so.id,
            period_label=b1.period_label, created_by=actor)
        conf.confirm(db, sc, confirmed_by_customer="TY客户签字人-王经理")
        db.commit()
        print(f"  确认单 {sc.id} — {sc.status} 签字人={sc.confirmed_by_customer}")

        # ====== Step 16: 开票 + 回款 + 核销 ======
        print("【16】开票 → 回款 → 核销")
        # 销售开票（7月租金）
        inv_s = inv.create_invoice(db, contract_id=sales_contract.id,
            amount=SALES_MONTHLY_INCL, invoice_no="SI-2026-07",
            issue_date=date(2026, 7, 5), due_date=date(2026, 8, 5))
        # 回款
        inv.mark_paid(db, inv_s.id, date(2026, 7, 10))
        # 收款流水
        txn_income = cap.record_transaction(db, created_by=actor, project_id=pid,
            source_type="租金收入", direction="IN", amount=SALES_MONTHLY_INCL,
            transaction_date=date(2026, 7, 10), category="租金",
            note="TY 7月租金", contract_id=sales_contract.id)
        # 核销：匹配发票与收款流水
        inv.reconcile_invoice(db, invoice_id=inv_s.id, txn_id=txn_income.id,
            reconciled_by=actor)
        db.commit()
        print(f"  销售发票 {inv_s.id} {SALES_MONTHLY_INCL} → 已回款 → 已核销")

        # 采购收票
        inv_p = inv.create_invoice(db, contract_id=purchase_contract.id,
            amount=PURCHASE_INCL, invoice_no="PI-001",
            issue_date=date(2026, 4, 15), due_date=date(2026, 4, 30))
        inv.mark_paid(db, inv_p.id, date(2026, 4, 30))
        db.commit()
        print(f"  采购发票 {inv_p.id} {PURCHASE_INCL} → 已付款")

        # ====== Step 17: 盈利测算 vs 实际 ======
        print("【17】盈利测算：测算版 vs 系统实际数据版对比")
        # 测算版（手动参数）
        est_params = {
            "purchase_ex_tax": float(PURCHASE_AMOUNT_EX),
            "purchase_incl_tax": float(PURCHASE_INCL),
            "monthly_rent": float(SALES_MONTHLY_INCL),
            "term_months": 60, "annual_rate": 0.04, "lease_term": 60,
            "payment_freq": "月", "repayment_method": "等额本息",
            "depreciation_years": 5, "residual_rate": 0.10,
            "monthly_opex": 0, "tax_rate": 0.06, "equity_ratio": 0.10,
        }
        est_result = profit.calculate_model(profit.ProfitInput(**est_params))
        profit.save_scenario(db, project_id=pid, name="基准方案（测算版）",
            params_json=est_params, result_json=est_result, is_actual=False, created_by=actor)

        # 实际版（从系统数据自动提取）
        actual_result = profit.calculate_for_project(db, str(pid))
        profit.save_scenario(db, project_id=pid, name="实际数据版",
            params_json={"source": "系统实际数据"}, result_json=actual_result,
            is_actual=True, created_by=actor)

        # 对比
        comparison = profit.compare_scenarios(db, project_id=pid)
        db.commit()

        summary = est_result.get("summary", {})
        actual_summary = actual_result.get("summary", {})
        print(f"\n{'='*60}")
        print(f"  测算 IRR={summary.get('irr_annual_pct')}%  NPV={summary.get('npv_5pct')}")
        print(f"  实际 IRR={actual_summary.get('irr_annual_pct')}%  NPV={actual_summary.get('npv_5pct')}")
        print(f"  差异项: {len(comparison.get('diffs', []))} 项")
        for d in comparison.get("diffs", []):
            print(f"    {d['key']}: 测算={d['estimated']} 实际={d['actual']} Δ={d['delta']}")

        # 资金池汇总
        s = cap.pool_summary(db)
        print(f"\n  资金池余额: {s['pool_balance']}  | 入 {s['total_in']}  出 {s['total_out']}")

        # 三流对账
        recon = inv.reconciliation(db)
        if recon:
            r0 = recon[0]
            print(f"  对账: 合同额{r0['contract_amount']} 应收{r0['billed']} 开票{r0['invoiced']} 收款{r0['received']}")

        print(f"\n===== 商机5090 全链路18步演示完成 =====")
    finally:
        db.close()


if __name__ == "__main__":
    run()
