"""EBS 接口 Mock 骨架（二期 W1-2）：字段映射配置 + 同步日志。

业财一体化出站基础：SIEGPU→EBS Mock（10 类业务域），entity_version 内容 hash 幂等。
与 alembic 0010 / db/schema.sql 双写一致；Mock 阶段仅出站（入站属期外里程碑）。
"""
import uuid
from datetime import datetime

from sqlalchemy import Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPK


class EbsFieldMapping(UUIDPK, TimestampMixin, Base):
    """字段映射配置：把 SIEGPU 实体字段映射到 EBS 字段，附转换规则。

    transform_rule 取值：direct（原值）/ date_format / decimal_scale / constant / …；
    transform_config 存规则参数（如 {scale:100, fmt:'YYYYMMDD', constant:'...'}）。
    """
    __tablename__ = "ebs_field_mappings"

    # 10 类业务域：customer/supplier/contract/invoice/asset/payment/prepayment/lease_disbursement/repayment/goods_receipt
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    siegpu_field: Mapped[str] = mapped_column(String(100), nullable=False)
    ebs_field: Mapped[str] = mapped_column(String(100), nullable=False)
    transform_rule: Mapped[str] = mapped_column(String(50), nullable=False, default="direct")
    transform_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class EbsSyncLog(UUIDPK, TimestampMixin, Base):
    """同步日志：每次 SIEGPU→EBS 出站写一行，entity_version 内容 hash 做幂等/乱序判定。

    幂等：同 entity_type + entity_id + entity_version 已有 SUCCESS/MOCK_SUCCESS 行 → 跳过（不新建 log）。
    """
    __tablename__ = "ebs_sync_logs"

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)  # 业务对象 id（UUID 序列化为字符串；兼容编号类）
    entity_version: Mapped[str] = mapped_column(String(64), nullable=False)  # 实体内容 hash
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="SIEGPU_TO_EBS")  # Mock 期仅出站
    sync_type: Mapped[str] = mapped_column(String(16), nullable=False)  # create/update/delete
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # SUCCESS / MOCK_SUCCESS / FAILED
    ebs_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)  # EBS 回执（Mock: MOCK-EBS-{uuid}）
    request_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
