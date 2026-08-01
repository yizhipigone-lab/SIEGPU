/** 角色代码 → 中文名映射（以 backend/app/seed.py 账号清单为准） */
export const ROLE_CN: Record<string, string> = {
  ADMIN: '管理员',
  FINANCE_DIRECTOR: '财务总监',
  FINANCE_STAFF: '财务专员',
  PROCUREMENT: '采购对接人',
  DELIVERY: '项目交付负责人',
}

/** 角色代码转中文名；空值返回 '—'，未知代码原样返回 */
export function roleName(code?: string | null): string {
  if (!code) return '—'
  return ROLE_CN[code] ?? code
}
