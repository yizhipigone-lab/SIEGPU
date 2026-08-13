"""采购退货端点（三期 §4.4）。main.py 挂 prefix=/api/returns。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.device import Device
from app.models.user import User
from app.schemas.return_order import ReturnAdvanceIn, ReturnCreate, ReturnDeviceOut, ReturnOut
from app.services import return_service as svc

router = APIRouter()


def _out(ro) -> dict:
    return ReturnOut.model_validate(ro).model_dump(mode="json")


@router.get("")
def list_returns(project_id: UUID | None = None, status: str | None = None,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = svc.list_returns(db, project_id=project_id, status=status)
    return {"items": [_out(r) for r in rows], "total": len(rows)}


@router.post("", status_code=201)
def create_return(payload: ReturnCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    ro = svc.create_return(db, actor_id=user.id, **payload.model_dump())
    db.commit()
    return _out(ro)


@router.get("/{rid}")
def get_return(rid: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ro = svc.get_return_or_404(db, rid)
    out = _out(ro)
    devices = []
    for r in svc.list_return_devices(db, ro.id):
        d = db.get(Device, r.device_id)
        row = ReturnDeviceOut.model_validate(r).model_dump(mode="json")
        row["sn"] = d.sn if d else None
        devices.append(row)
    out["devices"] = devices
    return out


@router.post("/{rid}/advance")
def advance_return(rid: UUID, payload: ReturnAdvanceIn,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """推进到下一状态（强顺序：申请→出库→收货→红票→退款核销）。"""
    ro = svc.advance_return(db, rid, actor_id=user.id,
                            transaction_date=payload.transaction_date)
    db.commit()
    return _out(ro)
