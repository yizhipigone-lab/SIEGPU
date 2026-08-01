"""文件上传/下载（合同/发票附件）。支持 PDF/DOC/DOCX/JPG/PNG/GIF。"""
import os
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.billing import Invoice
from app.models.project import Contract

router = APIRouter()

ALLOWED_EXT = {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.gif'}
MAX_SIZE = 20 * 1024 * 1024  # 20MB
ENTITY_MAP = {'contracts': Contract, 'invoices': Invoice}


@router.post('/{entity}/{eid}/upload')
def upload_file(entity: str, eid: UUID, file: UploadFile = File(...),
                db: Session = Depends(get_db), user=Depends(get_current_user)):
    model = ENTITY_MAP.get(entity)
    if not model:
        raise HTTPException(400, f'不支持上传到此实体: {entity}')
    obj = db.get(model, eid)
    if not obj:
        raise HTTPException(404, '记录不存在')
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f'不支持的类型: {ext}，仅支持 PDF/DOC/DOCX/JPG/PNG/GIF')
    contents = file.file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(400, '文件超过 20MB')
    stored = f'{uuid.uuid4().hex}{ext}'
    os.makedirs(settings.upload_dir, exist_ok=True)
    with open(os.path.join(settings.upload_dir, stored), 'wb') as f:
        f.write(contents)
    obj.file_path = stored
    db.commit()
    db.refresh(obj)
    return {'filename': file.filename, 'stored': stored, 'size': len(contents)}


@router.get('/{entity}/{eid}/file')
def download_file(entity: str, eid: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    model = ENTITY_MAP.get(entity)
    if not model:
        raise HTTPException(400, f'不支持: {entity}')
    obj = db.get(model, eid)
    if not obj or not obj.file_path:
        raise HTTPException(404, '无附件')
    path = os.path.join(settings.upload_dir, obj.file_path)
    if not os.path.exists(path):
        raise HTTPException(404, '文件不存在')
    return FileResponse(path, filename=obj.file_path)
