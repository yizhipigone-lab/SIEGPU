import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'

/**
 * 前后端共享常量（架构 #5 薄版）：后端 GET /api/meta/constants 是单一真源，
 * 前端启动后拉一次。拉取失败/字段缺失 → 逐字段回退到本地兜底（不阻塞启动）。
 *
 * 本地兜底刻意与后端 meta_service 同文：它是「后端不可达时的最后防线」，
 * 改了后端常量，前端照常渲染（可能短暂旧值），下次成功拉取即对齐。
 */

// —— 本地兜底（与后端 meta_service 同文）——
const FALLBACK_DEVICE_STAGES = ['订货', '在途', '到货', '己方压测', '上架', '客户压测', '点亮验收']

const FALLBACK_POOL_LABELS: Record<string, string> = {
  OWN: '自有资金池', LEASING: '金租池', BANK: '银行池', PREPAY: '预付款池(挂账)',
}

const FALLBACK_STEP_HINTS: Record<string, string> = {
  项目建立: '录入项目并选定流程模板，系统据此自动生成整个工作流',
  销售合同: '录入与客户的收入侧合同',
  采购合同: '录入与设备厂商的支出侧合同',
  销售订单: '面向客户的租出单据',
  采购订单: '面向设备厂商的购买单据',
  批次订单: '按采购批次下达的购买单据',
  银行流贷入金: '登记银行流动资金贷款到账',
  自有资金入金: '登记自有资金注入资金池',
  预付采购款: '向设备厂商支付预付款',
  金租申请: '向金租公司发起融资租赁申请',
  '金租放款+置换': '融资款到账，自动置换前期垫资并生成还款计划',
  金租放款: '融资款到账，自动生成还款计划',
  采购验收: '到货后做采购侧检验并审批通过',
  交付6阶段: '推进交付各阶段直至服务器上线',
  销售验收: '客户侧检验并审批通过',
  点亮: 'GPU 服务器上电联网，自动转资产并开始折旧',
  设备导入: '批量导入设备清单并逐台建档',
  设备到货: '确认设备送达现场并登记',
  设备上架: '设备装入机柜就位',
  点亮验收: '设备上电联网并通过检验，自动转资产',
  计费: '按上电周期生成账单（价税分离）',
  按台计费: '按设备台数与上电周期生成账单',
  客户确认: '客户对账单做确认或提出争议',
  '开票+回款+核销': '开具发票、登记回款并完成核销',
  盈利测算: '基于真实参数测算项目盈利并留存实际场景',
}

export const useMetaStore = defineStore('meta', () => {
  const deviceStages = ref<string[]>([...FALLBACK_DEVICE_STAGES])
  const poolLabels = ref<Record<string, string>>({ ...FALLBACK_POOL_LABELS })
  const stepHints = ref<Record<string, string>>({ ...FALLBACK_STEP_HINTS })
  const loaded = ref(false)

  /** 拉取后端常量。静默失败（本地兜底已就位）；幂等（只拉一次）。 */
  async function load() {
    if (loaded.value) return
    try {
      const { data } = await api.get('/meta/constants')
      if (Array.isArray(data?.DEVICE_STAGES) && data.DEVICE_STAGES.length) {
        deviceStages.value = data.DEVICE_STAGES
      }
      if (data?.POOL_LABELS && Object.keys(data.POOL_LABELS).length) {
        poolLabels.value = data.POOL_LABELS
      }
      if (data?.STEP_HINTS && Object.keys(data.STEP_HINTS).length) {
        stepHints.value = data.STEP_HINTS
      }
      loaded.value = true
    } catch {
      /* 后端不可达/未登录：本地兜底照常渲染 */
    }
  }

  function stepHint(name: string): string {
    return stepHints.value[name] ?? ''
  }

  /** 按给定顺序把 poolLabels 映射成 n-select 选项；未知 code 用 code 本身兜底。 */
  function poolOptions(order: string[]): Array<{ label: string; value: string }> {
    return order.map((v) => ({ label: poolLabels.value[v] ?? v, value: v }))
  }

  return { deviceStages, poolLabels, stepHints, loaded, load, stepHint, poolOptions }
})
