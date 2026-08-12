"""收入核算路径判定规则（二期 W3-4）—— 纯函数，无 DB 依赖。

规则（优先级从高到低，命中即停；父计划 §3.2 + D1 裁定：R1 用 '经营租赁'，与 schema 枚举对齐）：
  R1  经营租赁-自有：business_type=='经营租赁' AND leasing_mode=='自有' AND 合同==SALES → 经营租赁
  R1b 转租赁-金租：business_type=='经营租赁' AND leasing_mode IN ('直租','售后回租') AND 合同==SALES → 服务费（按月确认）
  R2  净额法：上游定价 + 存货风险上游 + 代理人 → 净额法
  R3  总额法：自主定价 + 存货风险我方 + 主要责任人（未命中 R1/R1b）→ 总额法
  R4  兜底 → 待判定（推送财务总监人工判定）

收入判定只针对 SALES 合同（收入侧）；PURCHASE 合同返回 method=None（不判定、不写快照）。
本模块只产出判定结果快照，不驱动收入确认动作（确认属三期 §4.2，D5 裁定）。
"""
from dataclasses import dataclass

# 判定结果枚举（与 contracts.revenue_method CHECK 一致）
METHODS = ("总额法", "净额法", "经营租赁", "服务费", "待判定")

# 判定输入枚举（与 contracts 三字段 CHECK 一致）
PRICING_AUTHORITIES = ("自主定价", "客户定价", "上游定价")
INVENTORY_RISK_BEARERS = ("我方", "客户", "上游")
PRINCIPAL_ROLES = ("主要责任人", "代理人")


@dataclass(frozen=True)
class JudgeResult:
    method: str | None  # 核算路径；PURCHASE 合同为 None（不判定）
    rule: str           # 命中规则号：R1/R1b/R2/R3/R4；不判定为 N/A
    basis: str          # 判定依据（自动生成，写 contracts.method_judge_basis）


def judge_revenue_method(*, business_type: str | None, leasing_mode: str | None,
                         contract_type: str, pricing_authority: str | None = None,
                         inventory_risk_bearer: str | None = None,
                         principal_role: str | None = None) -> JudgeResult:
    """判定收入核算路径。contract_type 非 SALES → 不判定（method=None）。"""
    if contract_type != "SALES":
        return JudgeResult(None, "N/A", "采购合同属成本侧，不参与收入核算路径判定")

    proj_ctx = f"项目业务类型={business_type or '未填'}，租赁模式={leasing_mode or '未填'}"

    # R1：经营租赁-自有（表内资产出租）—— D1 裁定用 '经营租赁'（schema 枚举值）
    if business_type == "经营租赁" and leasing_mode == "自有":
        return JudgeResult(
            "经营租赁", "R1",
            f"R1 命中：{proj_ctx}，销售合同 → 经营租赁（表内资产出租，租金按租赁期确认）")

    # R1b：转租赁-金租（直租/售后回租对外出租）—— 财务裁定 2026-08-04：全额按服务费逐月确认
    if business_type == "经营租赁" and leasing_mode in ("直租", "售后回租"):
        return JudgeResult(
            "服务费", "R1b",
            f"R1b 命中：{proj_ctx}，销售合同 → 服务费（收客户租金全额按服务费逐月确认；"
            "我方付金租租金按月进成本，收入成本同期配比）")

    input_ctx = (f"定价权={pricing_authority or '未填'}，存货风险承担={inventory_risk_bearer or '未填'}，"
                 f"角色={principal_role or '未填'}")

    # R2：净额法（代理人：上游定价 + 上游担风险）
    if (pricing_authority == "上游定价" and inventory_risk_bearer == "上游"
            and principal_role == "代理人"):
        return JudgeResult(
            "净额法", "R2",
            f"R2 命中：{input_ctx} → 净额法（代理人按净额确认收入）")

    # R3：总额法（主要责任人：自主定价 + 我方担风险，且未命中 R1/R1b）
    if (pricing_authority == "自主定价" and inventory_risk_bearer == "我方"
            and principal_role == "主要责任人"):
        return JudgeResult(
            "总额法", "R3",
            f"R3 命中：{input_ctx} → 总额法（主要责任人按总额确认收入）")

    # R4：兜底 → 待判定（推送财务总监人工判定）
    return JudgeResult(
        "待判定", "R4",
        f"R4 兜底：{proj_ctx}；{input_ctx} —— 未命中 R1/R1b/R2/R3，待财务总监人工判定")
