"""数据字典（通用探索层的基础）：白名单业务实体 + 字段中文标签。

设计动机（2026-08-27 用户拍板）：助手不该「问一个问题就手写一个工具」，
而是给 LLM 一套通用安全查询能力，让它自己看字典、自己组条件找答案。
安全边界：只读、白名单表与字段、参数化查询——LLM 永远拼不出裸 SQL。

敏感列不进字典（防注入诱导外泄）：口令哈希（users 表整体不开放）、
银行账号、联系电话。助手沿用当前用户权限，但攻击面宁小勿大。
"""
from __future__ import annotations

from app.models.asset import Asset
from app.models.billing import Billing, Invoice
from app.models.capital import CapitalAllocation, CapitalTransaction
from app.models.delivery import DeliveryStage, Order
from app.models.device import Device, DeviceStage
from app.models.leasing import LeasingNode, LeasingProcess
from app.models.master import Customer, EquipmentModel, Supplier
from app.models.project import Contract, Project
from app.models.repayment import Repayment
from app.models.sales_order import SalesOrder

# 通用字段中文标签（各实体共用口径）
COMMON_LABELS = {
    "id": "主键 UUID",
    "name": "名称", "code": "编号", "status": "状态", "notes": "备注",
    "project_id": "所属项目ID", "contract_id": "关联合同ID", "order_id": "关联订单ID",
    "amount": "金额（元）", "total_amount": "总金额（元）", "quantity": "数量",
    "unit_price": "单价（元）", "created_at": "创建时间", "updated_at": "更新时间",
    "start_date": "开始日期", "end_date": "结束日期",
}

ENTITY_LABELS: dict[str, dict[str, str]] = {
    "contracts": {"contract_no": "合同号", "type": "类型(SALES销售/PURCHASE采购)",
                  "direction": "收付方向(RECEIVABLE应收/PAYABLE应付)",
                  "amount": "合同额(不含税,元)", "amount_incl_tax": "合同额(含税,元)",
                  "monthly_rent": "月租金(含税,元)", "biz_type": "合同类型(算力租赁/转售/服务)",
                  "lease_months": "租期(月)", "tax_rate": "税率(小数)"},
    "orders": {"equipment_model_id": "设备型号ID", "order_date": "下单日期",
               "expected_delivery_date": "预计交付日期", "is_batch": "是否批次订单",
               "batch_name": "批次名", "total_amount": "订单总额(元)"},
    "sales_orders": {"monthly_rent_per_unit": "单台月租(元)", "total_monthly_rent": "月租合计(元)",
                     "equipment_model_id": "设备型号ID"},
    "devices": {"sn": "序列号", "monthly_price": "单台月计费额(元)",
                "purchase_value": "采购原值(元)", "leasing_mode": "租赁模式(自有/直租/售后回租)",
                "ownership": "权属", "prepayment_amount": "预付款分摊(元)",
                "equipment_model_id": "设备型号ID", "supplier_id": "供应商ID"},
    "device_stages": {"device_id": "设备ID", "stage": "阶段(订货/在途/到货/己方压测/上架/客户压测/点亮验收)",
                      "seq": "顺序(1-7)", "planned_date": "计划日期", "actual_date": "实际日期"},
    "delivery_stages": {"stage": "阶段(订货/到货/压测/运输在途/上架/点亮)", "seq": "顺序",
                        "planned_date": "计划日期", "actual_date": "实际日期"},
    "billings": {"period_index": "计费期数", "period_label": "期间标签", "billing_date": "计费日期",
                 "amount": "计费额(含税,元)", "amount_ex_tax": "不含税额(元)", "tax_amount": "税额(元)",
                 "device_id": "设备ID", "confirmation_status": "客户确认状态"},
    "invoices": {"invoice_no": "发票号", "direction": "方向(RECEIVABLE开给客户/PAYABLE供应商开来)",
                 "amount": "发票金额(含税,元)", "amount_ex_tax": "不含税金额(元)",
                 "due_date": "到期日", "paid_date": "实际收付日期"},
    "repayments": {"leasing_process_id": "金租流程ID", "period": "期数", "due_date": "应还日期",
                   "planned_principal": "计划本金(元)", "planned_interest": "计划利息(元)",
                   "actual_principal": "实还本金(元)", "actual_interest": "实还利息(元)",
                   "paid_date": "实还日期"},
    "capital_transactions": {"source_type": "来源类型(金租融资/银行流贷/回款/还款/调配/预付等)",
                             "direction": "方向(IN入金/OUT出金)", "transaction_date": "交易日期",
                             "pool": "资金池(OWN自有/LEASING金租/BANK银行/PREPAY预付)",
                             "category": "分类", "note": "摘要"},
    "capital_allocations": {"from_project_id": "调出项目ID", "to_project_id": "调入项目ID",
                            "allocation_date": "调配日期", "expected_return_date": "预计归还日期"},
    "assets": {"device_id": "设备ID", "unit_original_value": "单台原值(元)",
               "total_original_value": "原值合计(元)", "monthly_depreciation": "月折旧(元)",
               "residual_rate": "残值率(小数)", "operation_status": "运营状态"},
    "leasing_processes": {"supplier_id": "金租公司(供应商ID)", "total_amount": "申请金额(元)",
                          "actual_disbursement_amount": "实际放款(元)", "annual_rate": "年利率(小数)",
                          "term_periods": "期数", "payment_freq": "还款频率(月/季/半年)",
                          "repayment_method": "还款方式", "disbursement_date": "放款日期",
                          "financing_type": "融资类型"},
    "leasing_nodes": {"process_id": "金租流程ID", "node_name": "节点名", "seq": "顺序",
                      "planned_date": "计划日期", "actual_date": "实际日期",
                      "stuck_reason": "停滞原因"},
    "projects": {"total_investment": "预计总投入(元)", "business_type": "业务类型",
                 "leasing_mode": "租赁模式", "customer_id": "客户ID"},
    "suppliers": {"type": "类型(设备供应商/资金供应商/其他)", "is_leasing_org": "是否金租公司"},
    "customers": {"industry": "行业", "credit_rating": "信用评级"},
    "equipment_models": {"category": "分类(大卡/小卡/组网设备)", "gpu_type": "GPU型号",
                         "gpu_count": "GPU数量", "unit_price_reference": "参考单价(元)",
                         "resource_attr": "资源属性(自购资产/金租资产/转售资源)"},
}

# 敏感列：不进字典、不可查询（注入诱导外泄面）
DENY_FIELDS = {"bank_account", "contact_phone", "password_hash"}

ENTITIES: dict[str, dict] = {
    "projects": {"model": Project, "label": "项目"},
    "contracts": {"model": Contract, "label": "合同"},
    "orders": {"model": Order, "label": "采购订单"},
    "sales_orders": {"model": SalesOrder, "label": "销售订单"},
    "devices": {"model": Device, "label": "设备"},
    "device_stages": {"model": DeviceStage, "label": "设备阶段"},
    "delivery_stages": {"model": DeliveryStage, "label": "订单交付阶段"},
    "billings": {"model": Billing, "label": "计费单"},
    "invoices": {"model": Invoice, "label": "发票"},
    "repayments": {"model": Repayment, "label": "还款计划"},
    "capital_transactions": {"model": CapitalTransaction, "label": "资金流水"},
    "capital_allocations": {"model": CapitalAllocation, "label": "资金调配"},
    "assets": {"model": Asset, "label": "固定资产"},
    "leasing_processes": {"model": LeasingProcess, "label": "金租流程"},
    "leasing_nodes": {"model": LeasingNode, "label": "金租节点"},
    "suppliers": {"model": Supplier, "label": "供应商"},
    "customers": {"model": Customer, "label": "客户"},
    "equipment_models": {"model": EquipmentModel, "label": "设备型号"},
}


def describe(entity: str | None = None) -> dict:
    """数据字典：entity 为空 → 全部实体的概览；指定 → 该实体的字段明细。"""
    if entity and entity in ENTITIES:
        spec = ENTITIES[entity]
        labels = {**COMMON_LABELS, **ENTITY_LABELS.get(entity, {})}
        cols = []
        for col in spec["model"].__table__.columns:
            if col.name in DENY_FIELDS or col.name == "deleted_at":
                continue
            cols.append({"name": col.name, "type": str(col.type),
                         "label": labels.get(col.name, col.name)})
        return {"entity": entity, "label": spec["label"], "columns": cols}
    return {"entities": [{"entity": k, "label": v["label"]} for k, v in ENTITIES.items()],
            "hint": "用 entity 参数取某实体的字段明细，再用 query_data 组合条件查询"}


def allowed_fields(entity: str) -> set[str]:
    if entity not in ENTITIES:
        return set()
    return {c.name for c in ENTITIES[entity]["model"].__table__.columns
            if c.name not in DENY_FIELDS and c.name != "deleted_at"}