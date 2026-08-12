"""单据编号服务（二期 W9-10）：规则表驱动的编号生成 + 一期 SN 硬编码规则回迁（A8）。

格式：{prefix}{日期段}{分隔}{seq 左补零}。日期段由 date_format（YYYYMM/YYYYMMDD）从当天取；
无 date_format 则无日期段。跨日期段流水自动归零（current_period 跟踪）。

**回迁零变化铁律**：device_sn 规则（GPU- / YYYYMM / 5 位）生成结果必须与一期硬编码
`GPU-{yyyymm}-{seq:05d}` 完全一致——ensure_device_sn_rule 初始化时从存量设备读当月最大 seq
接续，test_doc_number 锁死「回迁前后下一个号相同」。
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.contract_ext import DocNumberRule
from app.models.device import Device

# doc_type → 默认规则（ensure 时无则建）
DEFAULT_RULES = {
    "device_sn": {"prefix": "GPU-", "date_format": "YYYYMM", "seq_digits": 5},
    "contract_no": {"prefix": "HT-", "date_format": "YYYYMM", "seq_digits": 4},
    "batch_no": {"prefix": "PC-", "date_format": "YYYYMM", "seq_digits": 4},
    "payment_no": {"prefix": "FK-", "date_format": "YYYYMMDD", "seq_digits": 4},
}


def _period_of(date_format: str | None, today: date) -> str:
    if not date_format:
        return ""
    if date_format == "YYYYMM":
        return f"{today:%Y%m}"
    if date_format == "YYYYMMDD":
        return f"{today:%Y%m%d}"
    return ""


def ensure_device_sn_rule(db: Session) -> DocNumberRule:
    """取 device_sn 规则（无则建）。初始化关键：从存量设备读当月最大 seq 接续，
    保证回迁后下一个 SN 与一期硬编码算法产出完全一致（A8 零变化）。"""
    rule = db.execute(select(DocNumberRule).where(
        DocNumberRule.doc_type == "device_sn")).scalar_one_or_none()
    if rule is not None:
        return rule
    cfg = DEFAULT_RULES["device_sn"]
    period = _period_of(cfg["date_format"], date.today())
    prefix = f"{cfg['prefix']}{period}-"
    last = db.execute(
        select(Device.sn).where(Device.sn.like(f"{prefix}%")).order_by(Device.sn.desc()).limit(1)
    ).scalar_one_or_none()
    last_seq = int(last.rsplit("-", 1)[1]) if last else 0
    rule = DocNumberRule(doc_type="device_sn", prefix=cfg["prefix"], date_format=cfg["date_format"],
                         seq_digits=cfg["seq_digits"], current_period=period, last_seq=last_seq)
    db.add(rule)
    db.flush()
    return rule


def ensure_rule(db: Session, doc_type: str) -> DocNumberRule:
    if doc_type == "device_sn":
        return ensure_device_sn_rule(db)
    rule = db.execute(select(DocNumberRule).where(
        DocNumberRule.doc_type == doc_type)).scalar_one_or_none()
    if rule is None:
        cfg = DEFAULT_RULES.get(doc_type)
        if cfg is None:
            raise ValueError(f"未知单据类型：{doc_type}（支持：{', '.join(DEFAULT_RULES)}）")
        rule = DocNumberRule(doc_type=doc_type, prefix=cfg["prefix"], date_format=cfg["date_format"],
                             seq_digits=cfg["seq_digits"])
        db.add(rule)
        db.flush()
    return rule


def next_number(db: Session, doc_type: str) -> str:
    """生成下一个编号（推进规则行流水；同事务随业务 commit）。跨日期段流水归零。"""
    rule = ensure_rule(db, doc_type)
    period = _period_of(rule.date_format, date.today())
    if period != (rule.current_period or ""):
        rule.current_period = period
        rule.last_seq = 0
    rule.last_seq += 1
    db.flush()
    sep = f"{period}-" if period else ""
    return f"{rule.prefix}{sep}{rule.last_seq:0{rule.seq_digits}d}"


def generate_device_sn(db: Session) -> str:
    """设备 SN 唯一入口（device_service.generate_sn 委托于此）。格式 GPU-{yyyymm}-{seq:05d}。"""
    return next_number(db, "device_sn")


# ------------------------------ 规则 CRUD（配置页/运维用） ------------------------------

def list_rules(db: Session) -> list[DocNumberRule]:
    return list(db.execute(select(DocNumberRule).order_by(DocNumberRule.doc_type)).scalars().all())
