from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import excel_service as svc

router = APIRouter()


@router.get("/export/{key}")
def export(key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    buf = svc.export_xlsx(db, key)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{key}.xlsx"'},
    )


@router.post("/import/{key}")
def import_(key: str, file: UploadFile, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = file.file.read()
    n = svc.import_xlsx(db, key, data)
    db.commit()
    return {"imported": n}
