import { glossary } from '../utils/glossary'
import { validators } from '../utils/validators'

export type FieldType = 'text' | 'number' | 'select' | 'date'

/** 远程下拉：从 endpoint 拉取选项。endpoint 传数组时合并多个来源，tags 用作来源前缀（如 [客户]/[供应商]）。 */
export interface RemoteOptions {
  endpoint: string | string[]
  label: string
  value: string
  tags?: string[]
}

export interface FieldConfig {
  key: string
  label: string
  type?: FieldType
  options?: { label: string; value: string }[]
  required?: boolean          // 红星 + 提交前前端校验
  remoteOptions?: RemoteOptions // 远程下拉（消灭 UUID 手填）
  hint?: string               // 字段术语大白话气泡（小白友好），见 utils/glossary.ts
  validate?: (value: any) => string | undefined  // 即时校验（小白防误填）：返回警告文案则标黄，见 utils/validators.ts
  section?: string            // 分组标题：表单中在该字段前渲染分割线（如「核算判定信息」）
  showWhen?: (form: Record<string, any>) => boolean  // 条件显示（如租期仅算力租赁）
  calc?: (form: Record<string, any>) => number | null  // 自动计算（如 不含税=含税/(1+税率)），可手工改
  calcDeps?: string[]                                  // calc 依赖字段，变化时重算本字段
  percent?: boolean           // 百分数输入：显示×100、提交/100（税率 13% ↔ 0.13）
  default?: any               // 新建时默认值（如税率默认 13）
}

export interface CrudConfig {
  title: string
  apiPath: string
  columns: string[]
  labels?: Record<string, string>
  fields: FieldConfig[]
  creatable?: boolean
  tagKeys?: string[]      // 这些列用 NTag 渲染（语义色）
  numKeys?: string[]      // 这些列用等宽数字 + 右对齐
  fileUpload?: boolean     // 支持文件上传（合同/发票）
  uploadEntity?: string    // 上传实体名（对应后端 /api/files/{entity}/...）
  importable?: boolean     // 支持 Excel 导入
  detailActions?: DetailAction[]
  detailTabs?: DetailTab[]
  stageFlow?: boolean       // 详情抽屉展示交付阶段列表 + 推进按钮（GET {apiPath}/{id}.stages，PATCH {apiPath}/delivery-stages/{stageId}）
  workspaceLink?: boolean   // 行操作列加「工作台」入口，跳 /projects/{id}/workspace（项目模块用）
  pdfExport?: boolean       // 行操作列加「PDF」按钮，blob 下载 {apiPath}/{id}/pdf 实时生成（F4，不落库）
  revenueJudge?: boolean    // 二期 W3-4：合同表单「核算判定信息」区实时预览判定结果（GET /contracts/judge-preview）
  auditEntity?: string      // 详情抽屉显示「操作记录」tab 的审计实体名（后端 audit_logs.entity_type，如 contract/order）
  listTabs?: { label: string; value: string }[]  // W4：列表顶部 Tab（value='' = 全部），非空 value 作为 listParamKey 查询参数
  listParamKey?: string     // Tab 对应的后端查询参数名（如 type / acceptance_type）
}

export interface DetailAction {
  label: string
  endpoint: string
  action: string
  method?: 'POST' | 'PATCH'
  showWhen?: (row: any) => boolean
  fields?: { key: string; label: string; type?: 'date' | 'select'; options?: { label: string; value: string }[]; required?: boolean }[]
  successMsg?: string
  tooltip?: string           // 按钮释义（NTooltip）
}

export interface DetailTab {
  label: string
  endpoint: string
  paramKey?: string
  columns: string[]
  labels?: Record<string, string>
}

const SUP_TYPE = [
  { label: '设备供应商', value: '设备供应商' },
  { label: '资金供应商', value: '资金供应商' },
  { label: '其他', value: '其他' },
]
const EQ_CAT = [{ label: '大卡', value: '大卡' }, { label: '小卡', value: '小卡' }, { label: '组网设备', value: '组网设备' }]
const CONTRACT_TYPE = [{ label: '销售 SALES', value: 'SALES' }, { label: '采购 PURCHASE', value: 'PURCHASE' }]
// 四期 W4：合同业务类型（与后端 contracts.biz_type CHECK 一致）
const BIZ_TYPE = ['算力租赁', '转售', '服务'].map((v) => ({ label: v, value: v }))
// 二期 W3-4：收入核算路径判定枚举（与后端 contracts CHECK / revenue_rules 一致）
const PRICING_AUTHORITY = ['自主定价', '客户定价', '上游定价'].map((v) => ({ label: v, value: v }))
const INVENTORY_RISK = ['我方', '客户', '上游'].map((v) => ({ label: v, value: v }))
const PRINCIPAL_ROLE = ['主要责任人', '代理人'].map((v) => ({ label: v, value: v }))
const REVENUE_METHOD = ['总额法', '净额法', '经营租赁', '服务费', '待判定'].map((v) => ({ label: v, value: v }))

export const MODULES: Record<string, CrudConfig> = {
  suppliers: {
    title: '供应商', apiPath: '/suppliers',
    columns: ['name', 'type', 'contact_person', 'contact_phone'],
    labels: { name: '名称', type: '类型', contact_person: '联系人', contact_phone: '电话' },
    tagKeys: ['type'],
    importable: true,
    fields: [
      { key: 'name', label: '名称' },
      { key: 'type', label: '类型', type: 'select', options: SUP_TYPE },
      { key: 'contact_person', label: '联系人' },
      { key: 'contact_phone', label: '电话' },
      { key: 'bank_account', label: '银行账户' },
      { key: 'notes', label: '备注' },
    ],
  },
  customers: {
    title: '客户', apiPath: '/customers',
    columns: ['name', 'industry', 'contact_person', 'credit_rating'],
    labels: { name: '名称', industry: '行业', contact_person: '联系人', credit_rating: '信用评级' },
    tagKeys: ['credit_rating'],
    importable: true,
    fields: [
      { key: 'name', label: '名称' },
      { key: 'industry', label: '行业' },
      { key: 'contact_person', label: '联系人' },
      { key: 'contact_phone', label: '电话' },
      { key: 'credit_rating', label: '信用评级' },
    ],
  },
  equipment: {
    title: '设备型号', apiPath: '/equipment-models',
    columns: ['name', 'category', 'gpu_type', 'gpu_count', 'unit_price_reference'],
    labels: { name: '型号', category: '类别', gpu_type: 'GPU', gpu_count: 'GPU数', unit_price_reference: '参考单价' },
    tagKeys: ['category'], numKeys: ['unit_price_reference'],
    fields: [
      { key: 'name', label: '型号' },
      { key: 'category', label: '类别', type: 'select', options: EQ_CAT },
      { key: 'gpu_type', label: 'GPU 类型' },
      { key: 'gpu_count', label: '单台 GPU 数', type: 'number', validate: validators.positiveInt },
      { key: 'memory', label: '显存' },
      { key: 'unit_price_reference', label: '参考单价(元)', type: 'number', hint: glossary('unit_price'), validate: validators.positiveAmount },
    ],
  },
  banks: {
    title: '银行', apiPath: '/banks',
    columns: ['name', 'credit_line', 'annual_rate'],
    labels: { name: '银行', credit_line: '授信额度', annual_rate: '年利率' },
    numKeys: ['credit_line', 'annual_rate'],
    fields: [
      { key: 'name', label: '银行名称' },
      { key: 'contact_person', label: '联系人' },
      { key: 'credit_line', label: '授信额度(元)', type: 'number', hint: glossary('credit_line'), validate: validators.positiveAmount },
      { key: 'annual_rate', label: '年利率(小数,如0.0435)', type: 'number', hint: glossary('annual_rate'), validate: validators.decimalRate },
    ],
  },
  projects: {
    title: '项目', apiPath: '/projects',
    columns: ['name', 'code', 'status', 'total_investment'],
    labels: { name: '项目', code: '编号', status: '状态', total_investment: '总投资' },
    tagKeys: ['status'], numKeys: ['total_investment'],
    workspaceLink: true,
    detailTabs: [
      { label: '合同', endpoint: '/contracts', paramKey: 'project_id', columns: ['contract_no', 'type', 'amount', 'status'], labels: { contract_no: '合同号', type: '类型', amount: '金额', status: '状态' } },
      { label: '订单', endpoint: '/orders', paramKey: 'project_id', columns: ['quantity', 'total_amount', 'status'], labels: { quantity: '数量', total_amount: '总额', status: '状态' } },
      { label: '金租', endpoint: '/leasing/processes', paramKey: 'project_id', columns: ['total_amount', 'status', 'disbursement_date'], labels: { total_amount: '融资额', status: '状态', disbursement_date: '放款日' } },
      { label: '资产', endpoint: '/assets', paramKey: 'project_id', columns: ['quantity', 'monthly_depreciation', 'status'], labels: { quantity: '数量', monthly_depreciation: '月折旧', status: '状态' } },
    ],
    fields: [
      { key: 'name', label: '项目名称' },
      { key: 'code', label: '项目编号' },
      { key: 'template_id', label: '流程模板', remoteOptions: { endpoint: '/workflows/templates', label: 'name', value: 'id' }, hint: '选流程模板：标准金租 18 步=完整链路（含资金入金/验收细分）；设备粒度 11 步=按设备逐台推进（更简单）。新手建议先用「设备粒度 11 步」。' },
      { key: 'total_investment', label: '总投资额(元)', type: 'number', hint: glossary('total_investment'), validate: validators.positiveAmount },
      { key: 'start_date', label: '开始日期', type: 'date' },
    ],
  },
  contracts: {
    title: '合同', apiPath: '/contracts',
    columns: ['contract_no', 'type', 'biz_type', 'direction', 'amount_incl_tax', 'amount', 'status', 'revenue_method'],
    labels: { contract_no: '合同号', type: '类型', biz_type: '合同类型', direction: '方向', amount_incl_tax: '金额(含税)', amount: '金额(不含税)', status: '状态', revenue_method: '核算路径' },
    tagKeys: ['type', 'biz_type', 'direction', 'status', 'revenue_method'], numKeys: ['amount_incl_tax', 'amount'],
    fileUpload: true, uploadEntity: 'contracts', pdfExport: true,
    listTabs: [{ label: '全部', value: '' }, { label: '销售合同', value: 'SALES' }, { label: '采购合同', value: 'PURCHASE' }],
    listParamKey: 'type',
    revenueJudge: true, auditEntity: 'contract',
    detailTabs: [
      { label: '发票', endpoint: '/invoices', paramKey: 'contract_id', columns: ['invoice_no', 'amount', 'status'], labels: { invoice_no: '发票号', amount: '金额', status: '状态' } },
      { label: '计费单', endpoint: '/billings', paramKey: 'contract_id', columns: ['period_label', 'amount', 'status'], labels: { period_label: '期间', amount: '金额(含税)', status: '状态' } },
      { label: '变更记录', endpoint: '/contracts/amendments', paramKey: 'contract_id', columns: ['amendment_date', 'change_type', 'reason'], labels: { amendment_date: '变更日', change_type: '类型', reason: '原因' } },
      { label: '终止记录', endpoint: '/contracts/terminations', paramKey: 'contract_id', columns: ['termination_date', 'reason', 'settlement_note'], labels: { termination_date: '终止日', reason: '原因', settlement_note: '结算说明' } },
    ],
    detailActions: [
      { label: '人工确认核算路径', endpoint: '/contracts', action: '/confirm-method',
        fields: [
          { key: 'method', label: '核算路径', type: 'select', options: REVENUE_METHOD, required: true },
          { key: 'reason', label: '覆盖/确认原因', required: true },
        ],
        showWhen: (r: any) => r.type === 'SALES',
        tooltip: '确认系统判定结果，或判定有误时人工覆盖；原因必填，全程留痕（审计 + 确认人/时间）',
        successMsg: '核算路径已确认/覆盖' },
      { label: '合同变更', endpoint: '/contracts', action: '/amendments',
        fields: [
          { key: 'change_type', label: '变更类型', type: 'select', options: ['金额变更', '月租变更', '期限变更', '其他'].map((v) => ({ label: v, value: v })), required: true },
          { key: 'new_amount', label: '新合同金额(可空)' },
          { key: 'new_monthly_rent', label: '新月租(可空)' },
          { key: 'reason', label: '变更原因', required: true },
        ],
        showWhen: (r: any) => r.status !== '已终止',
        tooltip: '金额/月租至少改一项；变更落合同即对未来期计费生效，前后快照留痕并同步 EBS',
        successMsg: '变更已生效' },
      { label: '合同终止', endpoint: '/contracts', action: '/terminate',
        fields: [
          { key: 'reason', label: '终止原因', required: true },
          { key: 'settlement_note', label: '结算说明(可空)' },
        ],
        showWhen: (r: any) => r.status !== '已终止',
        tooltip: '终止后合同不可再变更/计费请谨慎；终止记录留痕并同步 EBS',
        successMsg: '合同已终止' },
    ],
    fields: [
      { key: 'project_id', label: '项目', required: true, remoteOptions: { endpoint: '/projects', label: 'name', value: 'id' } },
      { key: 'type', label: '类型', type: 'select', options: CONTRACT_TYPE, required: true },
      { key: 'biz_type', label: '合同类型', type: 'select', options: BIZ_TYPE, hint: '业务性质：算力租赁（出租算力收租金）/ 转售（买断转卖）/ 服务（收服务费）' },
      { key: 'party_id', label: '对方(客户/供应商)', required: true, remoteOptions: { endpoint: ['/customers', '/suppliers'], label: 'name', value: 'id', tags: ['客户', '供应商'] } },
      { key: 'amount_incl_tax', label: '合同金额(含税,元)', type: 'number', required: true, hint: '合同上写的含税总额（客户实际要付的钱）', validate: validators.positiveAmount },
      { key: 'tax_rate', label: '税率%', type: 'number', percent: true, default: 13, hint: '增值税率，填百分数（如 13 表示 13%）' },
      // 不含税金额：默认按 含税/(1+税率) 自动算，仍可手工改（后端 amount 列=不含税口径，下游核算不变）
      { key: 'amount', label: '不含税金额(元)', type: 'number', required: true, hint: '不含税净额，默认按 含税÷(1+税率) 自动算，可手工修改', validate: validators.positiveAmount,
        calcDeps: ['amount_incl_tax', 'tax_rate'],
        calc: (form) => {
          const incl = form.amount_incl_tax
          if (incl === null || incl === undefined || incl === '') return null
          const rate = (form.tax_rate ?? 0) / 100
          return Math.round((incl / (1 + rate)) * 100) / 100
        } },
      { key: 'lease_months', label: '租期(月)', type: 'number', showWhen: (form) => form.biz_type === '算力租赁', hint: '仅算力租赁合同填写，如 36 / 60', validate: validators.positiveInt },
      { key: 'monthly_rent', label: '月租(含税,销售,元/月)', type: 'number', hint: glossary('monthly_rent'), validate: validators.positiveAmount },
      { key: 'contract_no', label: '合同号' },
      { key: 'pricing_authority', label: '定价权', type: 'select', options: PRICING_AUTHORITY, section: '核算判定信息（销售合同）', hint: '谁决定卖价：我方自主定价 / 客户说了算 / 上游供应商说了算（收入核算判定输入）' },
      { key: 'inventory_risk_bearer', label: '存货风险承担', type: 'select', options: INVENTORY_RISK, hint: '设备卖不掉/跌价的风险谁扛：我方 / 客户 / 上游（收入核算判定输入）' },
      { key: 'principal_role', label: '我方角色', type: 'select', options: PRINCIPAL_ROLE, hint: '主要责任人=对交付负全责（倾向总额法）；代理人=只撮合赚差价（倾向净额法）' },
    ],
  },
  orders: {
    title: '订单', apiPath: '/orders',
    columns: ['quantity', 'unit_price', 'total_amount', 'status'],
    labels: { quantity: '数量', unit_price: '单价', total_amount: '总额', status: '状态' },
    tagKeys: ['status'], numKeys: ['unit_price', 'total_amount'],
    stageFlow: true, auditEntity: 'order',
    detailActions: [
      { label: '点亮上线', endpoint: '/orders', action: '/light-on',
        fields: [{ key: 'actual_date', label: '点亮日', type: 'date' }],
        showWhen: (r: any) => r.status !== '已点亮',
        tooltip: '设备正式投产上线，点亮日=计费起点，将自动生成固定资产与折旧',
        successMsg: '点亮成功：已生成资产 + 月折旧' },
    ],
    fields: [
      { key: 'project_id', label: '项目', required: true, remoteOptions: { endpoint: '/projects', label: 'name', value: 'id' } },
      { key: 'equipment_model_id', label: '设备型号', required: true, remoteOptions: { endpoint: '/equipment-models', label: 'name', value: 'id' } },
      { key: 'quantity', label: '数量(台)', type: 'number', required: true, validate: validators.positiveInt },
      { key: 'unit_price', label: '单价(元)', type: 'number', required: true, hint: glossary('unit_price'), validate: validators.positiveAmount },
    ],
  },
  assets: {
    title: '资产', apiPath: '/assets',
    columns: ['quantity', 'total_original_value', 'monthly_depreciation', 'start_date', 'end_date', 'status'],
    labels: { quantity: '数量', total_original_value: '总原值', monthly_depreciation: '月折旧', start_date: '折旧起', end_date: '折旧止', status: '状态' },
    tagKeys: ['status'], numKeys: ['total_original_value', 'monthly_depreciation'],
    fields: [],
    creatable: false,
  },
}
