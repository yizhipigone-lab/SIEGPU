"""SIEGPU 全流程端到端跑通脚本（四期 W4 口径）。

一条新建业务从头跑到尾，覆盖：主数据 → 项目 → 销售合同 → 采购合同(参照) → 采购批次订单 →
设备 → 采购验收 → 在途/到货/上架/点亮 → 银行借款 → 预付 → 金租放款(基于验收) → 采购付款拆池 →
预付退回/核销 → 销售订单 → 销售验收 → 计费 → 对账单 → 客户确认 → 开票 → 收入确认 → 回款核销 → 确认还款。
每步打印 ✓ + 关键结果；最后打印 4 资金池余额 + 销售全链路对账。
直接打真实 HTTP API（localhost:8000），数据会出现在界面上。
"""
import sys
import requests

BASE = "http://localhost:8000/api"
TODAY = "2026-08-19"

# ---- 金额设定（算好口径，避免超合同拦截）----
SALES_EX = 1_000_000          # 销售合同 不含税 100 万
SALES_INCL = 1_130_000        # 销售合同 含税 113 万（税率13%）
PUR_EX = 442_477.88           # 采购合同 不含税
PUR_INCL = 500_000            # 采购合同 含税 50 万（< 销售含税 113 万，过 cap）
N_DEV = 2                     # 2 台设备
DEV_PRICE = 221_238.94        # 单台采购价（不含税），2 台 = PUR_EX
BANK_LOAN = 600_000           # 记银行借款 60 万
PREPAY = 200_000              # 预付 20 万（从银行池）
LEASE_DISB = 800_000          # 金租放款 80 万
SALE_INV_INCL = 113_000       # 销售首期开票 含税 11.3 万 → 不含税 10 万

step_no = 0
def step(title):
    global step_no
    step_no += 1
    print(f"\n[{step_no:02d}] {title}")

def ok(msg):
    print(f"      ✓ {msg}")

def die(msg):
    print(f"\n❌ 失败：{msg}")
    sys.exit(1)

# ---- 登录 ----
r = requests.post(f"{BASE}/auth/login", data={"username": "admin", "password": "sie123"})
if r.status_code != 200:
    die(f"登录失败 {r.status_code}: {r.text}")
TOK = r.json()["access_token"]
H = {"Authorization": f"Bearer {TOK}"}
print("登录成功 (admin)")

def post(path, body, expect=(200, 201)):
    r = requests.post(f"{BASE}{path}", json=body, headers=H)
    if r.status_code not in expect:
        die(f"POST {path} -> {r.status_code}: {r.text}")
    return r.json()

def patch(path, body=None, expect=(200,)):
    r = requests.patch(f"{BASE}{path}", json=body or {}, headers=H)
    if r.status_code not in expect:
        die(f"PATCH {path} -> {r.status_code}: {r.text}")
    return r.json()

def get(path, expect=(200,)):
    r = requests.get(f"{BASE}{path}", headers=H)
    if r.status_code not in expect:
        die(f"GET {path} -> {r.status_code}: {r.text}")
    return r.json()

def pools(pid):
    return get(f"/capital/pools?project_id={pid}")["pools"]

def show_pools(pid, tag=""):
    p = pools(pid)
    print(f"      资金池{tag}: 金租={p['LEASING']:,.0f} 银行={p['BANK']:,.0f} 预付挂账={p['PREPAY']:,.0f} 自有={p['OWN']:,.0f}")

# ================= 主数据 =================
step("主数据：客户 / 设备型号 / 设备供应商 / 金租供应商")
cust = post("/customers", {"name": "杭州云启科技", "industry": "互联网"})["id"]
eq = post("/equipment-models", {"name": "AMD MI350X", "category": "大卡", "gpu_type": "MI350X", "gpu_count": 8})["id"]
sup_dev = post("/suppliers", {"name": "深圳算力设备", "type": "设备供应商"})["id"]
sup_fin = post("/suppliers", {"name": "远东金租", "type": "资金供应商", "is_leasing_org": True})["id"]
ok("4 类主数据已建")

# ================= 项目 =================
step("创建项目（经营租赁 / 直租）")
proj = post("/projects", {"name": "云启算力租赁项目", "code": "YQ-001", "customer_id": cust,
                          "business_type": "经营租赁", "leasing_mode": "直租",
                          "total_investment": PUR_INCL})["id"]
ok(f"项目 id={proj[:8]}…")

# ================= 合同 =================
step("基于项目创建销售合同（算力租赁 / 含税113万 / 税率13% / 租期36月）")
sc = post("/contracts", {"project_id": proj, "type": "SALES", "biz_type": "算力租赁", "party_id": cust,
                         "amount": SALES_EX, "amount_incl_tax": SALES_INCL, "tax_rate": 0.13,
                         "lease_months": 36, "contract_no": "XS-2026-001"})
ok(f"销售合同 不含税={sc['amount']} 含税={sc['amount_incl_tax']} 类型={sc['biz_type']} 租期={sc['lease_months']}月")

step("基于销售合同创建采购合同（参照，含税50万 ≤ 销售113万）")
pc = post("/contracts", {"project_id": proj, "type": "PURCHASE", "biz_type": "算力租赁", "party_id": sup_dev,
                         "amount": PUR_EX, "amount_incl_tax": PUR_INCL, "tax_rate": 0.13,
                         "parent_contract_id": sc["id"], "contract_no": "CG-2026-001"})
ok(f"采购合同 含税={pc['amount_incl_tax']} 参照销售合同={pc.get('parent_contract_id','')[:8]}…")

# ================= 采购订单 + 设备 =================
step("创建采购批次订单 + 2 台设备挂批次")
po = post("/orders", {"project_id": proj, "contract_id": pc["id"], "equipment_model_id": eq,
                      "quantity": N_DEV, "unit_price": DEV_PRICE, "is_batch": True, "batch_name": "采购批次1"})
devs = []
for i in range(N_DEV):
    d = post("/devices", {"project_id": proj, "equipment_model_id": eq, "order_id": po["id"],
                          "monthly_price": 8333.33, "purchase_value": DEV_PRICE,
                          "leasing_mode": "直租", "ownership": "金租表外"})
    post("/devices/batch-assign", {"device_id": d["id"], "batch_id": po["id"]})
    devs.append(d["id"])
ok(f"采购批次订单 id={po['id'][:8]}…，挂 {len(devs)} 台设备")

# ================= 采购验收 → 在途 =================
step("采购验收（硬流转门1 前置）")
ar_p = post("/acceptances", {"project_id": proj, "acceptance_type": "采购验收", "order_id": po["id"],
                             "quantity_accepted": N_DEV, "inspector": "张三"})
post(f"/acceptances/{ar_p['id']}/approve", {})
ok(f"采购验收通过 id={ar_p['id'][:8]}…")

step("推进设备：在途→到货→己方压测→上架→客户压测→点亮验收")
for did in devs:
    for st in ["订货", "在途", "到货", "己方压测", "上架", "客户压测", "点亮验收"]:
        post(f"/devices/{did}/stage", {"stage": st, "status": "进行中"})
        body = {"stage": st, "status": "已完成"}
        if st == "点亮验收":
            body["actual_date"] = TODAY
        post(f"/devices/{did}/stage", body)
ok("2 台设备均点亮验收（已建资产卡）")

# ================= 资金池动作 =================
step("记银行借款 60 万 → 银行池")
post("/capital/bank-loan", {"project_id": proj, "amount": BANK_LOAN, "transaction_date": TODAY, "note": "工行流贷"})
show_pools(proj, "(借款后)")

step("预付 20 万（从银行池 → 预付款挂账池）")
post("/capital/prepayment", {"project_id": proj, "amount": PREPAY, "transaction_date": TODAY,
                             "contract_id": pc["id"], "from_pool": "BANK", "note": "预付设备款"})
show_pools(proj, "(预付后)")

# ================= 金租放款（基于采购验收） =================
step("金租流程：创建申请 → 基于采购验收放款 80 万 → 金租池↑ + 还款计划")
lp = post("/leasing/processes", {"project_id": proj, "supplier_id": sup_fin, "total_amount": LEASE_DISB,
                                 "annual_rate": 0.06, "term_periods": 3, "payment_freq": "月",
                                 "repayment_method": "等额本息", "start_date": TODAY})
dis = post(f"/leasing/processes/{lp['id']}/disbursements",
           {"amount": LEASE_DISB, "disbursement_date": TODAY, "acceptance_id": ar_p["id"], "note": "首批放款"})
ok(f"放款 80 万入金租池，生成还款计划；流水 pool=金租")
show_pools(proj, "(放款后)")

step("采购付款 30 万（拆分：金租池 20 万 + 银行池 10 万）")
pr = post("/payment-requests", {"project_id": proj, "contract_id": pc["id"], "direction": "OUT",
                                "amount": 300000, "reason": "采购设备款"})
# 审批通过
appr = get(f"/approvals?biz_type=付款申请&status=待审批")["items"]
my_appr = [a for a in appr if a["biz_id"] == pr["id"]][0]
post(f"/approvals/{my_appr['id']}/approve", {})
# 登记（拆池）
post(f"/payment-requests/{pr['id']}/disburse",
     {"transaction_date": TODAY, "pool_splits": [{"pool": "LEASING", "amount": 200000},
                                                  {"pool": "BANK", "amount": 100000}]})
ok("采购付款 30 万：金租池 20 万 + 银行池 10 万")
show_pools(proj, "(付款后)")

step("预付退回 8 万（供应商退回 → 预付款池↓ + 银行池↑）")
post("/capital/prepayment/refund", {"project_id": proj, "amount": 80000, "transaction_date": TODAY,
                                    "to_pool": "BANK", "note": "供应商退回部分预付"})
show_pools(proj, "(退回后)")

step("采购发票 50 万 + 预付核销 12 万（预付款池↓ 抵应付，不动现金）")
pinv = post("/invoices", {"contract_id": pc["id"], "amount": PUR_INCL, "invoice_no": "CG-INV-001", "issue_date": TODAY})
post("/capital/prepayment/offset", {"project_id": proj, "amount": 120000, "transaction_date": TODAY,
                                    "invoice_id": pinv["id"], "contract_id": pc["id"], "note": "预付核销抵应付"})
show_pools(proj, "(核销后)")

# ================= 销售侧：销售订单 → 验收 → 对账 → 开票 → 收入 =================
step("创建销售批次订单 + 挂 2 台已点亮设备")
so = post("/sales-orders", {"project_id": proj, "contract_id": sc["id"], "equipment_model_id": eq,
                            "quantity": N_DEV, "monthly_rent_per_unit": 8333.33,
                            "total_monthly_rent": 8333.33 * N_DEV, "is_batch": True, "batch_name": "销售批次1"})
for did in devs:
    post("/sales-orders/batch-assign", {"device_id": did, "sales_batch_id": so["id"]})
ok(f"销售批次订单 id={so['id'][:8]}…")

step("销售验收（硬流转门2/3 前置；勾上架）")
ar_s = post("/acceptances", {"project_id": proj, "acceptance_type": "销售验收", "sales_order_id": so["id"],
                             "quantity_accepted": N_DEV, "inspector": "李四", "shelve": True})
post(f"/acceptances/{ar_s['id']}/approve", {})
ok(f"销售验收通过 id={ar_s['id'][:8]}…")

step("按台计费（第1期）→ 生成应收计费单")
bills = []
for did in devs:
    b = post("/billings/device", {"device_id": did, "contract_id": sc["id"], "period_index": 1,
                                  "billing_date": TODAY})
    bills.append(b)
ok(f"2 台设备各出 1 期计费单（不含税 {bills[0]['amount_ex_tax']}）")

step("客户对账单（确认单）→ 客户确认（硬流转门4 前置）")
# 对账单按销售订单建（取第一期第一台设备的计费单挂确认）
conf = post("/confirmations", {"billing_id": bills[0]["id"], "sales_order_id": so["id"], "period_label": "2026-08"})
requests.post(f"{BASE}/confirmations/{conf['id']}/confirm", params={"confirmed_by_customer": "杭州云启科技"}, headers=H).raise_for_status()
ok("对账单已客户确认")

step("开票 11.3 万（含税）→ 自动确认收入（不含税 10 万）")
sinv = post("/invoices", {"contract_id": sc["id"], "amount": SALE_INV_INCL, "invoice_no": "XS-INV-001", "issue_date": TODAY})
ok(f"销售发票 含税={sinv['amount']} 不含税={sinv['amount_ex_tax']}")
recs = get(f"/revenue-recognitions?project_id={proj}")["items"]
rec = [r for r in recs if r.get("invoice_id") == sinv["id"]][0]
ok(f"自动出收入确认草稿：不含税={rec['amount']} 状态={rec['status']}")

step("审批通过收入确认 → 已确认/已同步EBS")
post(f"/approvals/{rec['approval_id']}/approve", {})
rec2 = [r for r in get(f"/revenue-recognitions?project_id={proj}")["items"] if r["id"] == rec["id"]][0]
ok(f"收入确认状态={rec2['status']}")

# ================= 回款核销 + 确认还款 =================
step("客户回款 11.3 万 → 应收核销（发票已核销）")
post(f"/invoices/{sinv['id']}/pay", {"paid_date": TODAY})
ok(f"发票已回款核销，状态={get(f'/invoices?contract_id=' + sc['id'])['items'][0]['status']}")

step("确认金租还款第 1 期")
reps = get(f"/repayments?leasing_process_id={lp['id']}")["items"]
r1 = sorted(reps, key=lambda x: x["period"])[0]
patch(f"/repayments/{r1['id']}", {"actual_principal": r1["planned_principal"],
                                  "actual_interest": r1["planned_interest"], "paid_date": TODAY})
ok(f"第1期还款已确认（计划本 {float(r1['planned_principal']):,.0f} + 息 {float(r1['planned_interest']):,.0f}）")

# ================= 汇总 =================
print("\n" + "=" * 60)
print("全流程跑通 ✅  最终状态汇总")
print("=" * 60)
show_pools(proj, "(最终)")
chain = get("/reconciliation-center/sales-chain")
mine = [r for r in chain["items"] if r["contract_id"] == sc["id"]]
if mine:
    m = mine[0]
    print(f"\n销售全链路对账（{m['contract_no']}）：")
    print(f"  合同额(不含税)={m['contract_amount']}  已计费={m['billed']}  已开票={m['invoiced']}  已收款={m['received']}  已确认收入={m['recognized']}")
    print(f"  差异标记: {m['flags'] or '无'}")
print(f"\n项目ID: {proj}")
print("到界面 http://localhost:8088 查看：项目/合同/订单/验收/资金/发票/收入确认/金租 各页均有这条业务。")
