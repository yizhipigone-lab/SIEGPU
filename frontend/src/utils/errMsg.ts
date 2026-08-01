/** 统一错误解析：把后端各类错误响应转成可读中文文案（单一来源）。 */

/** 常见字段名中文映射（与后端 RequestValidationError handler 保持一致）。 */
const FIELD_CN: Record<string, string> = {
  project_id: '项目', contract_id: '合同', order_id: '订单', sales_order_id: '销售订单',
  party_id: '往来单位', supplier_id: '供应商', customer_id: '客户', equipment_model_id: '设备型号',
  amount: '金额', quantity: '数量', price: '单价', unit_price: '单价',
  name: '名称', code: '编号', date: '日期', transaction_date: '交易日期',
  invoice_no: '发票号', status: '状态', note: '摘要', remark: '备注',
}

function fieldName(loc: unknown): string {
  const segs = Array.isArray(loc) ? loc : []
  const last = String(segs[segs.length - 1] ?? '')
  return FIELD_CN[last] ?? last
}

export function errMsg(e: any): string {
  const detail = e?.response?.data?.detail
  // BusinessError：detail = { code, message, details }
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) {
    return String(detail.message)
  }
  // detail 为字符串
  if (typeof detail === 'string' && detail) return detail
  // FastAPI 422 默认格式：detail = [{ loc, msg, type }, ...]
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((it: any) => `${fieldName(it?.loc)}: ${it?.msg ?? '参数错误'}`)
      .join('；')
  }
  return e?.message ?? '操作失败'
}
