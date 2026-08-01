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
}

export interface DetailAction {
  label: string
  endpoint: string
  action: string
  method?: 'POST' | 'PATCH'
  showWhen?: (row: any) => boolean
  fields?: { key: string; label: string; type?: 'date' }[]
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
      { key: 'gpu_count', label: '单台 GPU 数', type: 'number' },
      { key: 'memory', label: '显存' },
      { key: 'unit_price_reference', label: '参考单价', type: 'number' },
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
      { key: 'credit_line', label: '授信额度', type: 'number' },
      { key: 'annual_rate', label: '年利率(小数,如0.0435)', type: 'number' },
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
      { key: 'template_id', label: '流程模板', remoteOptions: { endpoint: '/workflows/templates', label: 'name', value: 'id' } },
      { key: 'total_investment', label: '总投资额', type: 'number' },
      { key: 'start_date', label: '开始日期', type: 'date' },
    ],
  },
  contracts: {
    title: '合同', apiPath: '/contracts',
    columns: ['contract_no', 'type', 'direction', 'amount', 'status'],
    labels: { contract_no: '合同号', type: '类型', direction: '方向', amount: '金额', status: '状态' },
    tagKeys: ['type', 'direction', 'status'], numKeys: ['amount'],
    fileUpload: true, uploadEntity: 'contracts',
    fields: [
      { key: 'project_id', label: '项目', required: true, remoteOptions: { endpoint: '/projects', label: 'name', value: 'id' } },
      { key: 'type', label: '类型', type: 'select', options: CONTRACT_TYPE, required: true },
      { key: 'party_id', label: '对方(客户/供应商)', required: true, remoteOptions: { endpoint: ['/customers', '/suppliers'], label: 'name', value: 'id', tags: ['客户', '供应商'] } },
      { key: 'amount', label: '合同金额(不含税)', type: 'number', required: true },
      { key: 'monthly_rent', label: '月租(含税,销售)', type: 'number' },
      { key: 'contract_no', label: '合同号' },
    ],
  },
  orders: {
    title: '订单', apiPath: '/orders',
    columns: ['quantity', 'unit_price', 'total_amount', 'status'],
    labels: { quantity: '数量', unit_price: '单价', total_amount: '总额', status: '状态' },
    tagKeys: ['status'], numKeys: ['unit_price', 'total_amount'],
    stageFlow: true,
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
      { key: 'quantity', label: '数量', type: 'number', required: true },
      { key: 'unit_price', label: '单价', type: 'number', required: true },
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
