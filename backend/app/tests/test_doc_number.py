"""单据编号测试（二期 W9-10）：SN 规则回迁零变化（A8）+ 新单据类型生成 + 跨段流水归零。

回迁铁律：device_sn 走 doc_number_rules 后，生成的 SN 必须与一期硬编码算法
（GPU-{yyyymm}-{当月最大seq+1:05d}）完全一致——本文件用「独立复算老算法」对照锁死。
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.contract_ext import DocNumberRule
from app.models.device import Device
from app.models.master import EquipmentModel
from app.models.project import Project
from app.services import device_service as dsvc
from app.services import doc_number_service as svc


def _old_algo_next_sn(db) -> str:
    """一期硬编码算法（独立复算，作对照真值）：GPU-{yyyymm}-{当月最大 seq +1}。"""
    prefix = f"GPU-{date.today():%Y%m}-"
    last = db.execute(
        select(Device.sn).where(Device.sn.like(f"{prefix}%")).order_by(Device.sn.desc()).limit(1)
    ).scalar_one_or_none()
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def _device(db):
    p = Project(name=f"P-{uuid.uuid4().hex[:6]}", code=f"c{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    e = EquipmentModel(name=f"M-{uuid.uuid4().hex[:6]}", category="大卡")
    db.add(e); db.flush()
    return dsvc.create_device(db, project_id=p.id, equipment_model_id=e.id,
                              purchase_value=Decimal("1"))


def test_sn_backfill_matches_old_algorithm(db):
    """A8 锁死：已存在 2 台设备（走新规则生成）→ 老算法复算的下一个号 == 新规则产出的下一个号。"""
    d1 = _device(db)
    d2 = _device(db)
    assert d1.sn == f"GPU-{date.today():%Y%m}-00001"
    assert d2.sn == f"GPU-{date.today():%Y%m}-00002"
    expected = _old_algo_next_sn(db)          # 老算法：00003
    got = svc.generate_device_sn(db)          # 新规则：也必须 00003
    assert got == expected == f"GPU-{date.today():%Y%m}-00003"
    # 规则行接续状态正确
    rule = db.execute(select(DocNumberRule).where(DocNumberRule.doc_type == "device_sn")).scalar_one()
    assert rule.last_seq == 3 and rule.current_period == f"{date.today():%Y%m}"


def test_sn_fresh_db_starts_at_one(db):
    assert svc.generate_device_sn(db) == f"GPU-{date.today():%Y%m}-00001"


def test_new_doc_types_formats(db):
    assert svc.next_number(db, "contract_no") == f"HT-{date.today():%Y%m}-0001"
    assert svc.next_number(db, "batch_no") == f"PC-{date.today():%Y%m}-0001"
    assert svc.next_number(db, "payment_no") == f"FK-{date.today():%Y%m%d}-0001"
    # 同类型递增
    assert svc.next_number(db, "contract_no") == f"HT-{date.today():%Y%m}-0002"


def test_period_rollover_resets_seq(db):
    """跨日期段流水归零（模拟规则行停在上月）。"""
    svc.next_number(db, "contract_no")
    rule = db.execute(select(DocNumberRule).where(DocNumberRule.doc_type == "contract_no")).scalar_one()
    rule.current_period = "202001"  # 伪造上月段
    db.flush()
    assert svc.next_number(db, "contract_no") == f"HT-{date.today():%Y%m}-0001"


def test_unknown_doc_type_raises(db):
    with pytest.raises(ValueError):
        svc.next_number(db, "unknown_doc")
