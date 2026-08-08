"""售后回租·回租出售全链路（一期 W7-8 §2.4）。

单事务 6 步（spec L293-297「自有阶段先转固 → 回租出售切已处置 + 表外 + 长期应付款」）：
  Step 0 守门：售后回租 / 表内自有 / 资产未处置 / 金租机构类型 / leasing_process 同项目
  Step 1 折旧截断：运营中资产按出售日截断（end_date=sale_date、operation_status=已处置），不动 monthly_depreciation
  Step 2 off_balance 建档（register_type=售后回租）
  Step 3 LongTermPayable 确认（principal=sale_price + 钩子位 carrying/gain_loss/original_end_date）
  Step 4 预付款 settled 标记
  Step 5 出售损益钩子位（只存值，不分录，二期 EBS）
  Step 6 审计 LEASEBACK_SALE

可逆性：本期不提供 reverse 端点（折旧截断后已过期间折旧不会自动红冲，机械回滚留悬挂态）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.leasing import LeasingProcess
from app.models.long_term_payable import LongTermPayable
from app.models.master import Supplier
from app.services import audit_service as audit
from app.services import device_service
from app.utils.depreciation import (
    carrying_amount,
    compute_sale_gain_loss,
    elapsed_whole_months,
)


def create_leaseback_sale(db: Session, *, device_id, sale_date: date, leasing_org_id,
                          sale_price: Decimal, leasing_process_id, note: str | None = None,
                          operator_id=None) -> dict:
    d = device_service.get_device_or_404(db, device_id)

    # ---- Step 0 守门 ----
    if d.leasing_mode != "售后回租":
        raise BusinessError("BAD_REQUEST", "仅售后回租设备可回租出售", 400)
    if d.ownership != "表内自有":
        raise BusinessError("STATE_ERROR", "设备非表内自有，无法回租出售（表外设备不走本流程）", 409)
    asset = db.execute(select(Asset).where(
        Asset.device_id == d.id, Asset.deleted_at.is_(None)
    )).scalar_one_or_none()
    if asset is None:
        raise BusinessError("STATE_ERROR", "设备尚未建资产卡（上架未完成），无法出售", 409)
    if asset.operation_status == "已处置":
        raise BusinessError("DUPLICATE", "设备已回租出售（已处置），不可重复出售", 409)
    org = db.get(Supplier, leasing_org_id)
    if org is None or org.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "金租机构不存在", 404)
    if org.type != "资金供应商":
        raise BusinessError("BAD_REQUEST", "leasing_org 必须为资金供应商", 400)
    proc = db.get(LeasingProcess, leasing_process_id)
    if proc is None or proc.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "leasing_process 不存在", 404)
    if proc.project_id != d.project_id:
        raise BusinessError("BAD_REQUEST", "leasing_process 与设备不属于同一项目", 400)

    # ---- Step 1 折旧截断（仅运营中资产；已转固未运营直接按原值） ----
    original_end = asset.end_date  # 原折旧到期日，二期 reverse 用（截断前捕获）
    if asset.operation_status == "运营中" and asset.start_date is not None \
            and asset.monthly_depreciation is not None:
        elapsed = elapsed_whole_months(asset.start_date, sale_date)
        carrying = carrying_amount(asset.total_original_value, asset.monthly_depreciation,
                                   elapsed, residual_value=asset.residual_value)
        asset.end_date = sale_date  # 折旧截断到出售日
    else:  # 已转固未运营（未起折旧）→ 账面 = 原值
        carrying = asset.total_original_value
    gain_loss = compute_sale_gain_loss(sale_price, carrying)
    asset.operation_status = "已处置"  # 不动 monthly_depreciation/status（保留原值审计）
    db.flush()

    # ---- Step 2 off_balance 建档（售后回租） ----
    off_balance = device_service.create_off_balance_register(
        db, device_id=d.id, register_type="售后回租",
        leasing_process_id=leasing_process_id, start_date=sale_date, note=note,
        operator_id=operator_id)

    # ---- Step 3 LongTermPayable 确认（per-device 唯一兜底幂等） ----
    payable = LongTermPayable(
        project_id=d.project_id, leasing_process_id=leasing_process_id,
        device_id=d.id, supplier_id=leasing_org_id,
        principal_amount=sale_price, carrying_amount=carrying,
        sale_gain_loss=gain_loss, original_end_date=original_end,
        paid_amount=Decimal("0"), status="已确认", confirm_date=sale_date,
    )
    db.add(payable)
    db.flush()

    # ---- Step 4 预付款 settled 标记（决策 3，仅标记；核销在二期） ----
    d.prepayment_settled = True

    # ---- Step 5 出售损益钩子位：已存入 payable.sale_gain_loss（不分录，二期 EBS） ----

    # ---- Step 6 审计 ----
    audit.log(db, user_id=operator_id, action="LEASEBACK_SALE", target_type="device",
              target_id=d.id,
              after_json={"sale_date": str(sale_date), "sale_price": str(sale_price),
                          "carrying_amount": str(carrying), "sale_gain_loss": str(gain_loss),
                          "leasing_process_id": str(leasing_process_id),
                          "long_term_payable_id": str(payable.id)})
    db.flush()
    return {
        "device_id": d.id, "asset_id": asset.id, "operation_status": asset.operation_status,
        "off_balance_register_id": off_balance.id, "long_term_payable_id": payable.id,
        "carrying_amount": carrying, "sale_gain_loss": gain_loss,
        "prepayment_settled": d.prepayment_settled,
    }
