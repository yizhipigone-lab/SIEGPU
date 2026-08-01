"""导入全部模型，便于 Alembic autogenerate 与 ORM 关系解析。"""
from app.models.acceptance import AcceptanceRecord
from app.models.asset import Asset
from app.models.base import Base
from app.models.billing import Billing, Invoice
from app.models.capital import CapitalAllocation, CapitalTransaction
from app.models.delivery import DeliveryStage, Order
from app.models.funding import FundingReplacement
from app.models.leasing import LeasingNode, LeasingProcess
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.profit_scenario import ProfitScenario
from app.models.project import Contract, Project
from app.models.project_workflow import ProjectWorkflow
from app.models.repayment import Repayment
from app.models.sales_order import SalesOrder
from app.models.service_confirmation import ServiceConfirmation
from app.models.step_audit_log import StepAuditLog
from app.models.user import AuditLog, IdempotencyKey, User
from app.models.workflow_template import WorkflowTemplate

__all__ = [
    "Base",
    "User", "AuditLog", "IdempotencyKey",
    "Supplier", "Customer", "EquipmentModel", "Bank",
    "Project", "Contract",
    "SalesOrder",
    "LeasingProcess", "LeasingNode",
    "CapitalTransaction", "CapitalAllocation",
    "FundingReplacement",
    "Order", "DeliveryStage",
    "AcceptanceRecord",
    "Billing", "Invoice",
    "Repayment",
    "Asset",
    "ProfitScenario",
    "ServiceConfirmation",
    "WorkflowTemplate", "ProjectWorkflow", "StepAuditLog",
]
