"""发票 OCR：tesseract 提取文字 + 正则解析中国增值税发票关键字段。

不依赖外部 API（完全本地），准确率取决于图片质量；用于预填表单，用户需人工校验。
"""
import io
import re

import pytesseract
from PIL import Image


def extract_text(image_bytes: bytes) -> str:
    """从图片/PDF（首页）字节提取中英文文字。"""
    img = Image.open(io.BytesIO(image_bytes))
    # 转灰度提升识别率
    if img.mode != 'L':
        img = img.convert('L')
    return pytesseract.image_to_string(img, lang='chi_sim+eng')


def parse_invoice(text: str) -> dict:
    """从 OCR 文本解析增值税发票关键字段（中英双语正则匹配，可能不全，用户校验）。"""
    result: dict[str, any] = {
        'raw_text': text[:600],
        'invoice_no': None, 'issue_date': None,
        'amount': None, 'amount_ex_tax': None, 'tax_amount': None, 'tax_rate': None,
    }

    def find_amount(pattern: str) -> float | None:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(',', '').replace('，', ''))
            except (ValueError, IndexError):
                return None
        return None

    # 发票号码
    m = re.search(r'(?:发票号码|Invoice\s*No)[：:.#\s]*(\d{8,20})', text, re.IGNORECASE)
    if not m:
        m = re.search(r'(\d{20})', text)  # 20 位全电发票号
    if m:
        result['invoice_no'] = m.group(1)

    # 开票日期
    m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text)
    if m:
        result['issue_date'] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    else:
        m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if m:
            result['issue_date'] = m.group(1)

    # 价税合计（含税）— 中英双语
    result['amount'] = find_amount(r'(?:价税合计|小写[）)]?|Total)[：:\s]*[（(]?[¥￥$]?\s*([\d,]+\.?\d*)')
    # 金额（不含税）
    result['amount_ex_tax'] = find_amount(r'(?:金额|Amount)[：:\s]*[（(]?[¥￥$]?\s*([\d,]+\.?\d*)')
    # 税额
    result['tax_amount'] = find_amount(r'(?:税额|Tax)[：:\s]*[（(]?[¥￥$]?\s*([\d,]+\.?\d*)')
    # 税率
    m = re.search(r'(?:税率|Rate)[：:\s]*(\d+)\s*%', text, re.IGNORECASE)
    if m:
        result['tax_rate'] = round(int(m.group(1)) / 100, 4)

    return result
