/**
 * 表单即时校验器（小白防误填）。
 *
 * 设计：返回「警告文案」→ 表单字段标黄 + 下方提示；返回 undefined → 通过。
 * 非阻断式（warning 不拦提交），与 ProfitView 百分比兜底一致——真正的非法值仍由后端兜底拒绝，
 * 前端只做「填错了赶紧提醒」的体验层提示（如把 4% 填成 4、把金额填成负数）。
 */
export type Validator = (value: any) => string | undefined

const isEmpty = (v: any) => v === '' || v === null || v === undefined

export const validators = {
  /** 金额必须 > 0（空值放行，必填由 required 控制）。 */
  positiveAmount: ((v) =>
    isEmpty(v) ? undefined : Number(v) <= 0 ? '金额必须大于 0' : undefined) as Validator,

  /** 数量为正整数（≥1，如 GPU 数/台数）。 */
  positiveInt: ((v) =>
    isEmpty(v) ? undefined
      : (!Number.isInteger(Number(v)) || Number(v) < 1) ? '请填正整数（≥1，如 8）' : undefined) as Validator,

  /** 百分比类小数 ≤ 1（0.04 表示 4%，防把 4% 填成 4）。 */
  decimalRate: ((v) =>
    isEmpty(v) ? undefined : Number(v) > 1 ? '请填小数（0.04 表示 4%），别填成 4' : undefined) as Validator,
}
