from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.device import (
    BatchAdvanceRequest,
    BatchAssign,
    BatchDeviceOut,
    BatchRemove,
    DeviceCreate,
    DeviceOut,
    DeviceStageAdvance,
    DeviceStageOut,
    DeviceUpdate,
    OffBalanceRegisterCreate,
    OffBalanceRegisterOut,
)
from app.schemas.leaseback_sale import LeasebackSaleCreate, LeasebackSaleOut
from app.services import device_service as svc
from app.services import leaseback_sale_service

router = APIRouter()


@router.get("")
def list_devices(project_id: UUID | None = None, batch_id: UUID | None = None,
                 status: str | None = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    rows = svc.list_devices(db, project_id=project_id, batch_id=batch_id, status=status)
    return {"items": [DeviceOut.model_validate(d).model_dump(mode="json") for d in rows], "total": len(rows)}


@router.get("/inventory-summary")
def inventory_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """设备可租库存看板：按型号聚合表内自有设备的 可租/在租/待交付 数量。"""
    return {"items": svc.inventory_summary(db)}


@router.post("", response_model=DeviceOut, status_code=201)
def create_device(payload: DeviceCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    d = svc.create_device(db, operator_id=user.id, **payload.model_dump())
    db.commit()
    return DeviceOut.model_validate(d)


@router.get("/off-balance-registers")
def list_off_balance(device_id: UUID | None = None, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    rows = svc.list_off_balance_registers(db, device_id=device_id)
    return {"items": [OffBalanceRegisterOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}


@router.post("/off-balance-registers", response_model=OffBalanceRegisterOut, status_code=201)
def create_off_balance(payload: OffBalanceRegisterCreate, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    r = svc.create_off_balance_register(db, operator_id=user.id, **payload.model_dump())
    db.commit()
    return OffBalanceRegisterOut.model_validate(r)


@router.post("/batch-assign", response_model=BatchDeviceOut, status_code=201)
def batch_assign(payload: BatchAssign, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    bd = svc.add_to_batch(db, device_id=payload.device_id, batch_id=payload.batch_id,
                          operator_id=user.id)
    db.commit()
    return BatchDeviceOut.model_validate(bd)


@router.post("/batch-remove", response_model=BatchDeviceOut)
def batch_remove(payload: BatchRemove, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    bd = svc.remove_from_batch(db, device_id=payload.device_id, operator_id=user.id)
    db.commit()
    return BatchDeviceOut.model_validate(bd)


@router.get("/batch-devices")
def list_batch_devices(batch_id: UUID | None = None, device_id: UUID | None = None,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_batch_devices(db, batch_id=batch_id, device_id=device_id)
    return {"items": [BatchDeviceOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}


@router.post("/import")
def import_devices(project_id: UUID, equipment_model_id: UUID, file: UploadFile,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = svc.import_devices(db, project_id=project_id, equipment_model_id=equipment_model_id,
                           filebytes=file.file.read(), operator_id=user.id)
    db.commit()
    return {"imported": n}


@router.post("/batch-advance")
def batch_advance(payload: BatchAdvanceRequest, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """批量推进：批内所有 active 设备推进同一节点。返回 {ok, fail}。"""
    result = svc.advance_batch_stages(
        db, batch_id=payload.batch_id, stage=payload.stage, status=payload.status,
        actual_date=payload.actual_date, attachment_path=payload.attachment_path,
        notes=payload.notes, operator_id=user.id,
    )
    db.commit()
    return result


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return DeviceOut.model_validate(svc.get_device_or_404(db, device_id))


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(device_id: UUID, payload: DeviceUpdate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    d = svc.update_device(db, device_id, operator_id=user.id, **payload.model_dump(exclude_unset=True))
    db.commit()
    return DeviceOut.model_validate(d)


@router.delete("/{device_id}")
def delete_device(device_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_device(db, device_id, operator_id=user.id)
    db.commit()
    return {"id": str(device_id), "deleted": True}


@router.get("/{device_id}/stages")
def list_device_stages(device_id: UUID, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """列设备的 7 节点状态（懒初始化后的行；未推进的设备可能无行）。"""
    rows = svc.list_device_stages(db, device_id)
    return {"items": [DeviceStageOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}


@router.post("/{device_id}/stage", response_model=DeviceOut)
def advance_stage(device_id: UUID, payload: DeviceStageAdvance, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """推进设备单节点（状态机校验 → 更新 device.status 物化列 → 同步批次聚合）。"""
    d, _ = svc.advance_device_stage(
        db, device_id=device_id, stage=payload.stage, status=payload.status,
        actual_date=payload.actual_date, attachment_path=payload.attachment_path,
        notes=payload.notes, operator_id=user.id,
    )
    db.commit()
    return DeviceOut.model_validate(d)


@router.post("/{device_id}/leaseback-sale", response_model=LeasebackSaleOut, status_code=200)
def leaseback_sale(device_id: UUID, payload: LeasebackSaleCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """售后回租·回租出售（独立动作+按钮，决策 1）。

    路径第二段为字面量 leaseback-sale，与 /{device_id}/stage 不互吞。
    全链路 6 步（折旧截断 + off_balance + 长期应付款 + 预付款 settled + 损益钩子 + 审计）。
    """
    result = leaseback_sale_service.create_leaseback_sale(
        db, device_id=device_id, sale_date=payload.sale_date,
        leasing_org_id=payload.leasing_org_id, sale_price=payload.sale_price,
        leasing_process_id=payload.leasing_process_id, note=payload.note, operator_id=user.id)
    db.commit()
    return LeasebackSaleOut(**result)
