import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class Device(UUIDPK, TimestampMixin, Base):
    """单台设备档案（一期 W1-2 新增核心实体）。

    status 为物化列：W1-2 允许创建时写入；W3-4 起由设备状态机单点维护，业务代码禁写。
    """

    __tablename__ = "devices"

    sn: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # GPU-{yyyymm}-{seq5}
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    sales_contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True)
    equipment_model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipment_models.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    monthly_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 单台月计费额
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 硬件配置
    leasing_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 自有/直租/售后回租（快照自项目）
    purchase_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 采购原值（单台）
    prepayment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)  # 预付款分摊
    status: Mapped[str] = mapped_column(String(20), default="订货", nullable=False)
    ownership: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 表内自有/金租表外/转售表外
    prepayment_settled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 一期 W7-8：售后回租预付款结转标记（回租出售时置 True）
    # 二期 W9-10（D2 裁定）：预付款累计已结转额，复用 devices 单源（不建 prepayments 表）；NULL 按 0 计
    prepayment_settled_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class DeviceStage(UUIDPK, TimestampMixin, Base):
    """设备节点状态（一期 W3-4 设备粒度新路径）。

    一台设备 7 个节点行（订货/在途/到货/己方压测/上架/客户压测/点亮验收），懒初始化：
    首次 advance_device_stage 时创建。device.status 物化列由这些行派生（_derive_device_status）。
    """

    __tablename__ = "device_stages"

    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)  # 订货/在途/到货/己方压测/上架/客户压测/点亮验收
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-7
    status: Mapped[str] = mapped_column(String(20), default="未开始", nullable=False)  # 未开始/进行中/已完成/不合格
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 验收报告/物流单/压测报告
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BatchDevice(UUIDPK, TimestampMixin, Base):
    """批次-设备组合关系（留痕）。同一台设备全局仅允许一条 active 记录（service 层强制）。"""

    __tablename__ = "batch_devices"

    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # 加入/移出
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    operated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class OffBalanceRegister(UUIDPK, TimestampMixin, Base):
    """表外设备备查台账（独立于 assets，避免污染折旧汇总）。"""

    __tablename__ = "off_balance_registers"

    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    register_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 金租直租/售后回租/转售
    leasing_process_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leasing_processes.id"), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
