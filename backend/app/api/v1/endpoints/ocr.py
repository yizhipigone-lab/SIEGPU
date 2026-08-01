"""发票 OCR 端点：上传发票图片/PDF → tesseract 提取 → 解析关键字段 → 返回预填数据。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.deps import get_current_user
from app.models.user import User
from app.services.ocr_service import extract_text, parse_invoice

router = APIRouter()


@router.post('/invoice')
def ocr_invoice(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """上传发票图片 → 返回 OCR 解析的 invoice_no / amount / date 等字段（用户需校验）。"""
    allowed = {'.jpg', '.jpeg', '.png', '.pdf', '.bmp', '.tiff'}
    ext = '.' + (file.filename or '').rsplit('.', 1)[-1].lower() if '.' in (file.filename or '') else ''
    if ext not in allowed:
        raise HTTPException(400, f'OCR 仅支持图片/PDF，收到: {ext or "未知"}')
    try:
        img_bytes = file.file.read()
        text = extract_text(img_bytes)
        result = parse_invoice(text)
        result['filename'] = file.filename
        return result
    except Exception as e:
        return {'error': str(e), 'raw_text': '', 'invoice_no': None,
                'amount': None, 'amount_ex_tax': None, 'tax_amount': None,
                'issue_date': None, 'tax_rate': None}
