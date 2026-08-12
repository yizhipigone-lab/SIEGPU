# W5-6 币种与汇率 —— 单位量纲全链路对照表（D6 动工前前置检查）

> 日期：2026-08-12 ｜ 依据：二期执行计划 §5 W5-6 + §7「动工前出对照表」验收门 + 审计铁律 §6-7（混合单位是 bug 重灾区）
> 用途：W5-6 所有金额/汇率代码与 golden 算例的唯一量纲依据。任何一处转换不按本表 → 视为 bug。

## 0. 总原则

- **率（rate）存全精度，钱（amount）两位小数**。率永不四舍五入（DECIMAL(18,8) 原样存取）；只有「率 × 金额 → 金额」这一跳才 q2（ROUND_HALF_UP，见 `utils/reconcile.q2` / `utils/billing.q2`）。
- **amount 列的币种归属由同行 `currency_code` 决定**；`currency_code IS NULL` = 人民币（存量行语义不变，零迁移成本）。
- **base_amount 恒为人民币**（本币），只在 `currency_code ≠ 本币` 时有值；本币流水 base_amount 留 NULL（不冗余复制 amount，防双源漂移）。
- 汇率为**直接标价法**：`rate = 1 单位外币兑多少人民币`（USD 7.10 = 1 美元 = 7.10 元）。换算永远 `本币 = 外币 × rate`，除法只在「本币 ÷ rate → 外币」反算时出现（W5-6 不用，留 W11-12）。

## 1. 逐字段对照表

| 字段（表） | 输入单位 | 存储单位 | 计算单位 | 输出单位 | 转换点 |
|---|---|---|---|---|---|
| `currencies.code` | ISO 字母码（USD） | VARCHAR(10) 大写 | — | 原样 | 入参 `.upper()` 归一 |
| `exchange_rates.rate` | 1 外币 = N 元人民币（如 7.10） | DECIMAL(18,8) 全精度 | Decimal 原样（不 round） | 原样展示 8 位 | 无转换（原样存取）；校验 `rate > 0` |
| `exchange_rates.effective_date` | 生效日期 | DATE | 取值：`effective_date <= 业务日` 的最大者 | 原样 | 取值规则见 §2 |
| `contracts.booked_rate` | 签约日记账汇率 | DECIMAL(18,8) | Decimal 原样 | 原样 | 手填或按签约日取 exchange_rates |
| `invoices.invoice_rate` | 开票日汇率 | DECIMAL(18,8) | Decimal 原样 | 原样 | 同上（开票日） |
| `billings.booked_rate` | 计费日记账汇率 | DECIMAL(18,8) | Decimal 原样 | 原样 | 同上（计费日） |
| `capital_transactions.settlement_rate` | 实际结售汇汇率 | DECIMAL(18,8) | Decimal 原样 | 原样 | 收付实现时的真实成交率 |
| `capital_transactions.amount` | 交易币种金额（外币或人民币） | DECIMAL(18,2) | Decimal | 两位 | 写入前 q2 |
| `capital_transactions.base_amount` | **人民币**金额 | DECIMAL(18,2) | `q2(amount × settlement_rate)` | 两位 | **唯一乘除跳**：外币 × 率 → q2 人民币 |
| 汇兑损益 diff | — | 不落字段（落成一条 capital_transactions） | `q2(foreign_amount × (invoice_rate − settlement_rate))` | 两位人民币 | 见 §3 golden |

## 2. 汇率取值规则（exchange_service.get_rate）

1. `from == to`（含同为本币）→ 返回 `Decimal(1)`，不查表。
2. 查 `from_currency/to_currency` 且 `effective_date <= 业务日`，按 `effective_date DESC` 取第一条（**最近不未来**）。
3. 无记录 → `BusinessError("NOT_FOUND", ...)`，**不静默按 1 折算**（静默=假账）。
4. `rate_type`（中间价/卖出价…）参与筛选；本阶段只用 `中间价`，其余枚举留扩展。

## 3. 汇兑损益口径（核销触发，invoice_service.reconcile_invoice 钩子）

- 触发条件（缺一不可，否则不动）：发票与流水**同币种**、该币种**非本币**、`invoice_rate` 与 `settlement_rate` **都已填**。
- 公式（应收/收款式样，采购付款同式、方向相反）：
  `diff = q2(txn.amount × (invoice.invoice_rate − txn.settlement_rate))`
  - `diff > 0`（结算率 < 开票率，人民币升值→收得少=损失）→ 记 **OUT**（损失）
  - `diff < 0`（结算率 > 开票率→收得多=收益）→ 记 **IN**（收益），金额取 `abs(diff)`
  - `diff = 0` → **不落任何记录**（golden 零例断言的就是「无记录」）
- 落账：`capital_transactions(source_type='汇兑损益', category='汇兑损益', contract_id, transaction_date=结算流水日, idempotency_key=f'fx:{txn.id}')`。
  - **⚠️ 不得填 `invoice_id`**：`Invoice.matched_amount` 是「Σ 该发票关联流水」，填了会把损益计入已核销金额，污染核销口径（W3-4 复审实测确认此坑）。
  - 损益行 `currency_code` 留 NULL（它已是人民币金额，amount 即本币，无需再换算）。
- 设备维度分摊（按成本占比）：**W11-12 接通**（payment_settlements 就绪后），本阶段只到合同级落账。

## 4. Golden 算例（手算真值，测试追值断言）

| 例 | 外币额 | invoice_rate | settlement_rate | 手算 diff | 期望 |
|---|---|---|---|---|---|
| G1 收益 | USD 10,000 | 7.10 | 7.20 | 10000×(7.10−7.20) = **−1,000.00** | IN 1,000.00 元 |
| G2 损失 | USD 10,000 | 7.20 | 7.10 | 10000×(7.20−7.10) = **+1,000.00** | OUT 1,000.00 元 |
| G3 零 | USD 10,000 | 7.10 | 7.10 | 0 | 无记录 |
| G4 精度 | USD 33,333.33 | 7.12345678 | 7.10000000 | 33333.33×0.02345678 = 781.8926…→ **781.89** | OUT 781.89（验证全精度率参与计算、只在最终 q2） |
| G5 base_amount | USD 10,000 × 7.12345678 | — | — | 71,234.5678 → **71,234.57** | base_amount=71,234.57 |
