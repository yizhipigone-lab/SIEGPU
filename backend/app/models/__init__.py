"""导入全部模型，便于 Alembic autogenerate 与 ORM 关系解析。"""
from app.models.acceptance import AcceptanceRecord
from app.models.asset import Asset
from app.models.base import Base
from app.models.billing import Billing, Invoice
from app.models.capital import CapitalAllocation, CapitalTransaction
from app.models.delivery import DeliveryStage, Order
from app.models.contract_ext import (ContractAmendment, ContractTermination,
                                     DocNumberRule, LeasingRuleConfig)
from app.models.currency import Currency, ExchangeGainLossRule, ExchangeRate
from app.models.device import BatchDevice, Device, DeviceStage, OffBalanceRegister
from app.models.ebs import EbsFieldMapping, EbsSyncLog
from app.models.funding import FundingReplacement
from app.models.insurance import InsuranceConfig, InsurancePolicy, InsurancePolicyDevice
from app.models.leasing import LeasingDisbursement, LeasingNode, LeasingProcess
from app.models.long_term_payable import LongTermPayable
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.notification import Notification
from app.models.payment import Approval, PaymentRequest, PaymentSettlement
from app.models.profit_scenario import ProfitScenario
from app.models.project import Contract, Project
from app.models.project_workflow import ProjectWorkflow
from app.models.repayment import Repayment
from app.models.revenue import GlAccountMapping, RevenueRecognition
from app.models.return_order import ReturnOrder, ReturnOrderDevice
from app.models.sales_order import SalesBatchDevice, SalesOrder
from app.models.service_confirmation import ServiceConfirmation
from app.models.step_audit_log import StepAuditLog
from app.models.user import AuditLog, IdempotencyKey, User
from app.models.workflow_template import WorkflowTemplate

__all__ = [
    "Base",
    "User", "AuditLog", "IdempotencyKey",
    "Supplier", "Customer", "EquipmentModel", "Bank",
    "Project", "Contract",
    "Notification",
    "SalesOrder", "SalesBatchDevice",
    "LeasingProcess", "LeasingNode", "LeasingDisbursement",
    "LongTermPayable",
    "CapitalTransaction", "CapitalAllocation",
    "Currency", "ExchangeRate", "ExchangeGainLossRule",
    "InsurancePolicy", "InsurancePolicyDevice", "InsuranceConfig",
    "ContractAmendment", "ContractTermination", "DocNumberRule", "LeasingRuleConfig",
    "Approval", "PaymentRequest", "PaymentSettlement",
    "RevenueRecognition", "GlAccountMapping",
    "ReturnOrder", "ReturnOrderDevice",
    "FundingReplacement",
    "Order", "DeliveryStage",
    "Device", "BatchDevice", "DeviceStage", "OffBalanceRegister",
    "EbsFieldMapping", "EbsSyncLog",
    "AcceptanceRecord",
    "Billing", "Invoice",
    "Repayment",
    "Asset",
    "ProfitScenario",
    "ServiceConfirmation",
    "WorkflowTemplate", "ProjectWorkflow", "StepAuditLog",
]
