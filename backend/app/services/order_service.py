"""订单/交付服务。建订单自动生成 6 交付阶段；点亮=计费起点，同事务生成资产（W20）。"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.models.asset import Asset
from app.models.delivery import DeliveryStage, Order
from app.models.master import EquipmentModel
from app.models.project import Project
from app.utils.depreciation import depreciation_inputs
from app.utils.repayment_plan import add_months

STAGES = ["订货", "到货", "压测", "运输在途", "上架", "点亮"]

STAGE_TRANSITIONS = {
    "未开始": {"进行中"},
    "进行中": {"已完成"},
    "已完成": set(),
}


def create_order(db: Session, *, project_id, equipment_model_id=None, quantity=None,
                 unit_price=None, contract_id=None, order_date=None,
                 expected_delivery_date=None, is_batch=False, batch_name=None,
                 disbursement_threshold_pct=None) -> Order:
    if not db.get(Project, project_id):
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    # W7-8 决策 2：阈值缺省→100（与列 NOT NULL DEFAULT 100 对齐，避免显式传 None 撞约束）。
    threshold_pct = Decimal("100") if disbursement_threshold_pct is None else disbursement_threshold_pct
    if is_batch:
        # 一期 W3-4 discipline ①：批次行 4 字段可空（跨型号组合），汇总值由批内设备聚合派生；
        # 且不生成 6 条 delivery_stages——节点只走 device_stages。
        o = Order(
            project_id=project_id, contract_id=contract_id, equipment_model_id=equipment_model_id,
            quantity=quantity, unit_price=unit_price, total_amount=None, order_date=order_date,
            expected_delivery_date=expected_delivery_date, status="已下单",
            is_batch=True, batch_name=batch_name, flow_type="batch",
            disbursement_threshold_pct=threshold_pct,
        )
        db.add(o)
        db.flush()
        return o
    if not db.get(EquipmentModel, equipment_model_id):
        raise BusinessError("NOT_FOUND", "设备型号不存在", 404)
    total = (quantity * unit_price)
    o = Order(
        project_id=project_id, contract_id=contract_id, equipment_model_id=equipment_model_id,
        quantity=quantity, unit_price=unit_price, total_amount=total, order_date=order_date,
        expected_delivery_date=expected_delivery_date, status="已下单",
        is_batch=is_batch, batch_name=batch_name,
        disbursement_threshold_pct=threshold_pct,
    )
    db.add(o)
    db.flush()
    for i, st in enumerate(STAGES, 1):
        db.add(DeliveryStage(order_id=o.id, stage=st, seq=i, status="未开始"))
    db.flush()
    return o


def list_orders(db: Session, project_id=None):
    stmt = select(Order).order_by(Order.created_at.desc())
    if project_id:
        stmt = stmt.where(Order.project_id == project_id)
    return db.execute(stmt).scalars().all()


# 订单编辑白名单（四期修补：此前订单无 PATCH 端点，前端编辑报 405）
_UPDATEABLE = ("project_id", "contract_id", "equipment_model_id", "quantity", "unit_price",
               "order_date", "expected_delivery_date", "disbursement_threshold_pct", "batch_name")
# 已点亮后禁改的资产字段（数量/单价/型号已据 total_amount 生成固定资产，改了会与资产卡片不一致）
_ASSET_DRIVING = ("quantity", "unit_price", "equipment_model_id")


def update_order(db: Session, order_id, *, actor_id=None, **fields) -> Order:
    o = db.get(Order, order_id)
    if not o or o.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "订单不存在", 404)
    if o.status == "已点亮" and any(fields.get(k) is not None for k in _ASSET_DRIVING):
        raise BusinessError("ILLEGAL_TRANSITION", "订单已点亮投产，数量/单价/型号已生成固定资产，不可再改", 409)
    if fields.get("project_id") is not None and not db.get(Project, fields["project_id"]):
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    if fields.get("equipment_model_id") is not None and not db.get(EquipmentModel, fields["equipment_model_id"]):
        raise BusinessError("NOT_FOUND", "设备型号不存在", 404)
    for k, v in fields.items():
        if k in _UPDATEABLE and v is not None:
            setattr(o, k, v)
    # 非批次订单：数量/单价变化 → 重算总额（批次订单总额由批内设备聚合派生，不在此算）
    if not o.is_batch and o.quantity is not None and o.unit_price is not None:
        o.total_amount = o.quantity * o.unit_price
    db.flush()
    return o


def get_order_with_stages(db: Session, order_id):
    o = db.get(Order, order_id)
    if not o or o.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "订单不存在", 404)
    stages = db.execute(
        select(DeliveryStage).where(DeliveryStage.order_id == order_id).order_by(DeliveryStage.seq)
    ).scalars().all()
    return o, stages


def advance_stage(db: Session, *, stage_id, status, actual_date=None) -> DeliveryStage:
    st = db.get(DeliveryStage, stage_id)
    if not st or st.deleted_at is not None:
        raise BusinessError("NOT_FOUND", "交付阶段不存在", 404)
    # 一期 W3-4 discipline ②：设备粒度订单禁走旧 6 节点（防批次/单台双推进双计）
    from app.services import device_service as dsvc
    o = db.get(Order, st.order_id)
    if o is not None:
        dsvc.assert_legacy_path(db, o)
    allowed = STAGE_TRANSITIONS.get(st.status, set())
    if status not in allowed:
        raise BusinessError("ILLEGAL_TRANSITION", f"阶段不允许 {st.status} → {status}", 409)
    st.status = status
    if status == "已完成" and actual_date:
        st.actual_date = actual_date
    db.flush()
    return st


def light_on(db: Session, *, order_id, actual_date: date, operator_id=None):
    """点亮：同事务把'点亮'阶段置完成、订单置已点亮、生成资产（W20）。幂等：订单状态守卫。"""
    o = db.execute(select(Order).where(Order.id == order_id).with_for_update()).scalar_one_or_none()
    if not o:
        raise BusinessError("NOT_FOUND", "订单不存在", 404)
    # 一期 W3-4 discipline ②：设备粒度订单走 device_stages 点亮验收，禁走旧 light_on（防双重建卡/出账）
    from app.services import device_service as dsvc
    dsvc.assert_legacy_path(db, o)
    if o.status == "已点亮":
        raise BusinessError("DUPLICATE", "订单已点亮", 409)
    # 点亮阶段 → 已完成
    point_stage = db.execute(
        select(DeliveryStage).where(DeliveryStage.order_id == order_id, DeliveryStage.stage == "点亮")
    ).scalar_one()
    point_stage.status = "已完成"
    point_stage.actual_date = actual_date
    # 生成资产 + 折旧（复用 utils/depreciation）
    dep = depreciation_inputs(o.total_amount)
    asset = Asset(
        project_id=o.project_id, equipment_model_id=o.equipment_model_id, order_id=o.id,
        quantity=o.quantity, unit_original_value=o.unit_price, total_original_value=o.total_amount,
        residual_value=dep["residual_value"], depreciable_value=dep["depreciable_value"],
        annual_depreciation=dep["annual_depreciation"], monthly_depreciation=dep["monthly_depreciation"],
        start_date=actual_date, end_date=add_months(actual_date, 60), status="折旧中",
        operation_status="运营中",  # W5-6：legacy 点亮即起折旧=运营中（与 device 路径激活一致）
    )
    db.add(asset)
    o.status = "已点亮"
    db.flush()
    from app.services import audit_service as _audit
    _audit.log(db, user_id=operator_id, action="LIGHT_ON", target_type="order",
               target_id=o.id, after_json={"quantity": o.quantity, "date": str(actual_date)})
    return o, asset
