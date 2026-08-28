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


@router.get("/devices-template")
def devices_template(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """缺陷#2：设备导入模版；缺陷#11：表头中文化（导入端中英表头都识别）。"""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "列说明"
    ws.append(["列名（中文表头，英文旧表头也认）", "说明"])
    ws.append(["SN 序列号", "留空自动生成 GPU-{yyyymm}-{seq}；可填已有SN"])
    ws.append(["金租模式", "自有 / 直租 / 售后回租"])
    ws.append(["单台月计费额(元)", "数字，如 10000"])
    ws.append(["单台采购原值(元)", "数字，如 960000"])
    ws.append(["预付款分摊(元)", "数字，不付填 0"])
    ws.append(["权属", "表内自有 / 金租表外 / 转售表外"])
    ws2 = wb.create_sheet("示例数据")
    ws2.append(["SN 序列号", "金租模式", "单台月计费额(元)", "单台采购原值(元)", "预付款分摊(元)", "权属"])
    ws2.append(["", "自有", 10000, 960000, 0, "表内自有"])
    ws2.append(["", "直租", 8333.33, 442477.88, 200000, "金租表外"])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=devices-template.xlsx"},
    )


@router.post("/import/{key}")
def import_(key: str, file: UploadFile, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = file.file.read()
    n = svc.import_xlsx(db, key, data)
    db.commit()
    return {"imported": n}
