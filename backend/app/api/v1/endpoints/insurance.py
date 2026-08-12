"""保险管理端点（二期 W7-8）。main.py 挂 prefix=/api/insurance。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.device import Device
from app.models.user import User
from app.schemas.insurance import (AmortizationRow, ClaimIn, ConfigIn, ConfigOut, PolicyCreate,
                                   PolicyDeviceOut, PolicyOut)
from app.services import insurance_service as svc

router = APIRouter()


def _policy_out(p) -> dict:
    return PolicyOut.model_validate(p).model_dump(mode="json")


@router.get("/policies")
def list_policies(project_id: UUID | None = None, policy_type: str | None = None,
                  status: str | None = None,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_policies(db, project_id=project_id, policy_type=policy_type, status=status)
    return {"items": [_policy_out(p) for p in rows], "total": len(rows)}


@router.post("/policies", status_code=201)
def create_policy(payload: PolicyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = svc.create_policy(db, actor_id=user.id, **payload.model_dump())
    db.commit()
    return _policy_out(p)


@router.get("/policies/{pid}")
def get_policy(pid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = svc.get_policy_or_404(db, pid)
    out = _policy_out(p)
    devices = []
    for r in svc.list_policy_devices(db, p.id):
        d = db.get(Device, r.device_id)
        row = PolicyDeviceOut.model_validate(r).model_dump(mode="json")
        row["sn"] = d.sn if d else None
        devices.append(row)
    out["devices"] = devices
    return out


@router.post("/policies/{pid}/confirm")
def confirm_policy(pid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = svc.confirm_policy(db, pid, actor_id=user.id)
    db.commit()
    return _policy_out(p)


@router.post("/policies/{pid}/collect")
def collect_to_asset(pid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """保费归集进资产原值（点亮前窗口硬约束；点亮后 409 拒，走长期待摊）。"""
    p = svc.collect_to_asset(db, pid, actor_id=user.id)
    db.commit()
    return _policy_out(p)


@router.post("/policies/{pid}/claims", status_code=201)
def register_claim(pid: UUID, payload: ClaimIn,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = svc.register_claim(db, pid, actor_id=user.id, **payload.model_dump())
    db.commit()
    return _policy_out(p)


@router.get("/policies/{pid}/amortization", response_model=list[AmortizationRow])
def policy_amortization(pid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """长期待摊摊销计划预览（本阶段只产出计划项）。"""
    return svc.policy_amortization(db, pid)


@router.get("/configs")
def list_configs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_configs(db)
    return {"items": [ConfigOut.model_validate(c).model_dump(mode="json") for c in rows], "total": len(rows)}


@router.post("/configs", response_model=ConfigOut, status_code=201)
def create_config(payload: ConfigIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = svc.create_config(db, **payload.model_dump())
    db.commit()
    return ConfigOut.model_validate(c)
