from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.order import (
    DeliveryStageOut,
    LightOnRequest,
    OrderCreate,
    OrderDetail,
    OrderOut,
    StageAdvance,
)
from app.services import order_service as svc

router = APIRouter()


@router.get("")
def list_orders(project_id: UUID | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_orders(db, project_id=project_id)
    return {"items": [OrderOut.model_validate(o).model_dump(mode="json") for o in rows], "total": len(rows)}


@router.post("", response_model=OrderDetail, status_code=201)
def create_order(payload: OrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    o = svc.create_order(db, **payload.model_dump())
    db.commit()
    _, stages = svc.get_order_with_stages(db, o.id)
    # 自检迭代修正：补齐 is_batch/batch_name/batch_status/flow_type 4 字段。
    # list_orders 用 model_validate 已吐真值，此处手工构造曾遗漏→批次订单响应 is_batch=False（说谎）。
    return OrderDetail(
        id=o.id, project_id=o.project_id, equipment_model_id=o.equipment_model_id, contract_id=o.contract_id,
        quantity=o.quantity, unit_price=o.unit_price, total_amount=o.total_amount, status=o.status,
        is_batch=o.is_batch, batch_name=o.batch_name, batch_status=o.batch_status, flow_type=o.flow_type,
        disbursement_threshold_pct=o.disbursement_threshold_pct,
        disbursement_todo_process_id=o.disbursement_todo_process_id,
        stages=[DeliveryStageOut.model_validate(s) for s in stages],
    )


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(order_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    o, stages = svc.get_order_with_stages(db, order_id)
    return OrderDetail(
        id=o.id, project_id=o.project_id, equipment_model_id=o.equipment_model_id, contract_id=o.contract_id,
        quantity=o.quantity, unit_price=o.unit_price, total_amount=o.total_amount, status=o.status,
        is_batch=o.is_batch, batch_name=o.batch_name, batch_status=o.batch_status, flow_type=o.flow_type,
        disbursement_threshold_pct=o.disbursement_threshold_pct,
        disbursement_todo_process_id=o.disbursement_todo_process_id,
        stages=[DeliveryStageOut.model_validate(s) for s in stages],
    )


@router.patch("/delivery-stages/{stage_id}")
def advance_stage(stage_id: UUID, payload: StageAdvance, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    st = svc.advance_stage(db, stage_id=stage_id, status=payload.status, actual_date=payload.actual_date)
    db.commit()
    return {"id": str(st.id), "status": st.status}


@router.post("/{order_id}/light-on")
def light_on(order_id: UUID, payload: LightOnRequest, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    o, asset = svc.light_on(db, order_id=order_id, actual_date=payload.actual_date, operator_id=user.id)
    db.commit()
    return {"order_id": str(o.id), "status": o.status, "asset_id": str(asset.id),
            "monthly_depreciation": asset.monthly_depreciation}
