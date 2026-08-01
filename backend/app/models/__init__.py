"""导入全部模型，便于 Alembic autogenerate 与 ORM 关系解析。"""
from app.models.asset import Asset
from app.models.base import Base
from app.models.billing import Billing, Invoice
from app.models.capital import CapitalAllocation, CapitalTransaction
from app.models.delivery import DeliveryStage, Order
from app.models.leasing import LeasingNode, LeasingProcess
from app.models.master import Bank, Customer, EquipmentModel, Supplier
from app.models.project import Contract, Project
from app.models.repayment import Repayment
from app.models.user import AuditLog, IdempotencyKey, User

__all__ = [
    "Base",
    "User", "AuditLog", "IdempotencyKey",
    "Supplier", "Customer", "EquipmentModel", "Bank",
    "Project", "Contract",
    "LeasingProcess", "LeasingNode",
    "CapitalTransaction", "CapitalAllocation",
    "Order", "DeliveryStage",
    "Billing", "Invoice",
    "Repayment",
    "Asset",
]
