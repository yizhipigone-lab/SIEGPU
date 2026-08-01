"""订单/交付服务。建订单自动生成 6 交付阶段；点亮=计费起点，同事务生成资产（W20）。"""
from datetime import date

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


def create_order(db: Session, *, project_id, equipment_model_id, quantity, unit_price,
                 contract_id=None, order_date=None, expected_delivery_date=None) -> Order:
    if not db.get(Project, project_id):
        raise BusinessError("NOT_FOUND", "项目不存在", 404)
    if not db.get(EquipmentModel, equipment_model_id):
        raise BusinessError("NOT_FOUND", "设备型号不存在", 404)
    total = (quantity * unit_price)
    o = Order(
        project_id=project_id, contract_id=contract_id, equipment_model_id=equipment_model_id,
        quantity=quantity, unit_price=unit_price, total_amount=total, order_date=order_date,
        expected_delivery_date=expected_delivery_date, status="已下单",
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
    allowed = STAGE_TRANSITIONS.get(st.status, set())
    if status not in allowed:
        raise BusinessError("ILLEGAL_TRANSITION", f"阶段不允许 {st.status} → {status}", 409)
    st.status = status
    if status == "已完成" and actual_date:
        st.actual_date = actual_date
    db.flush()
    return st


def light_on(db: Session, *, order_id, actual_date: date):
    """点亮：同事务把'点亮'阶段置完成、订单置已点亮、生成资产（W20）。幂等：订单状态守卫。"""
    o = db.execute(select(Order).where(Order.id == order_id).with_for_update()).scalar_one_or_none()
    if not o:
        raise BusinessError("NOT_FOUND", "订单不存在", 404)
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
    )
    db.add(asset)
    o.status = "已点亮"
    db.flush()
    return o, asset
