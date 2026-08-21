<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NCard, NEmpty, NForm, NFormItem, NInputNumber, NModal, NSelect, NSpin, NTag, useMessage,
} from 'naive-ui'
import { ChevronDown, ChevronRight, Plus } from 'lucide-vue-next'
import { http } from '../api/client'
import { errMsg } from '../utils/errMsg'
import { money, statusTagType } from '../utils/format'

/**
 * 项目血缘树：项目 → 销售合同 →（销售订单+对账单；发票；参照的采购合同 → 采购订单 → 预付款 + 单台设备穿透）；
 * 项目 → 金租申请（可从本卡直接发起，预填项目）。数据来自 GET /projects/{id}/relationships（后端一次聚合）。
 * 预付款口径：devices 单源按采购订单聚合 —— 已付挂账 / 部分核销 / 已回核销。
 */
const props = defineProps<{ projectId: string }>()
const router = useRouter()
const msg = useMessage()
const tree = ref<any>(null)
const loading = ref(false)
/** 采购订单 id → 是否展开单台设备明细（单台穿透） */
const expanded = ref<Record<string, boolean>>({})

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/projects/${props.projectId}/relationships`)
    tree.value = data
  } catch (e: any) { msg.error(errMsg(e)) }
  finally { loading.value = false }
}
onMounted(load)
watch(() => props.projectId, load)

/** 预付款状态 → 语义色（已付挂账=黄 / 部分核销=蓝 / 已回核销=绿 / 无预付款=灰） */
function ppType(s: string): 'success' | 'info' | 'warning' | 'default' {
  if (s === '已回核销') return 'success'
  if (s === '部分核销') return 'info'
  if (s === '已付挂账') return 'warning'
  return 'default'
}

function toggle(orderId: string) { expanded.value[orderId] = !expanded.value[orderId] }

function go(path: string, query: Record<string, string> = {}) {
  router.push({ path, query: { project_id: props.projectId, ...query } })
}

// —— 发起金租申请（预填本项目，资金供应商远程下拉） ——
const showLease = ref(false)
const fundSuppliers = ref<{ label: string; value: string }[]>([])
const leaseForm = reactive({
  supplier_id: null as string | null,
  total_amount: null as number | null,
  annual_rate: null as number | null,  // 百分数输入（4 = 4%），提交 ÷100
  term_periods: 12,
  payment_freq: '月',
  repayment_method: '等额本息',
})
const FREQ_OPTS = ['月', '季', '半年'].map((v) => ({ label: v, value: v }))
const REPAY_OPTS = ['等额本息', '等额本金'].map((v) => ({ label: v, value: v }))

async function openLease() {
  if (!fundSuppliers.value.length) {
    try {
      const { data } = await http.get('/suppliers')
      fundSuppliers.value = (data.items || [])
        .filter((s: any) => s.type === '资金供应商')
        .map((s: any) => ({ label: s.name, value: s.id }))
    } catch { /* 下拉为空不阻断，提交时后端校验 */ }
  }
  showLease.value = true
}

async function submitLease() {
  if (!leaseForm.supplier_id || !leaseForm.total_amount) { msg.warning('请选金租机构并填写申请金额'); return }
  try {
    await http.post('/leasing/processes', {
      project_id: props.projectId,
      supplier_id: leaseForm.supplier_id,
      total_amount: leaseForm.total_amount,
      annual_rate: leaseForm.annual_rate != null ? leaseForm.annual_rate / 100 : null,
      term_periods: leaseForm.term_periods,
      payment_freq: leaseForm.payment_freq,
      repayment_method: leaseForm.repayment_method,
    })
    msg.success('金租申请已发起')
    showLease.value = false
    Object.assign(leaseForm, { supplier_id: null, total_amount: null, annual_rate: null })
    await load()
  } catch (e: any) { msg.error(errMsg(e)) }
}
</script>

<template>
  <n-spin :show="loading">
    <div v-if="tree">
      <!-- 金租申请（项目级，leasing_processes.project_id 强制挂钩） -->
      <n-card size="small" style="margin-bottom:12px;border-left:4px solid #7C3AED">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-weight:600">金租申请（{{ tree.leasing_processes.length }}）</span>
            <n-button size="tiny" type="primary" quaternary @click="openLease">
              <template #icon><Plus :size="14" /></template>
              发起金租申请
            </n-button>
          </div>
        </template>
        <div v-if="tree.leasing_processes.length === 0" style="color:#94A3B8;font-size:13px">
          暂无金租申请
        </div>
        <div
          v-for="lp in tree.leasing_processes" :key="lp.id"
          style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #F1F5F9;cursor:pointer"
          @click="go('/leasing')"
        >
          <n-tag size="small" :bordered="false" type="warning">{{ lp.financing_type || lp.leasing_mode || '金租' }}</n-tag>
          <span style="flex:1">{{ lp.supplier_name || '—' }}</span>
          <span class="num" style="color:#64748B">申请 {{ money(lp.total_amount) }}</span>
          <span v-if="lp.actual_disbursement_amount" class="num" style="color:#64748B">
            已放款 {{ money(lp.actual_disbursement_amount) }}
          </span>
          <n-tag size="small" :type="statusTagType(lp.status) as any">{{ lp.status }}</n-tag>
        </div>
      </n-card>

      <!-- 销售合同卡片树 -->
      <n-card
        v-for="sc in tree.sales_contracts" :key="sc.id" size="small"
        style="margin-bottom:12px;border-left:4px solid #2563EB"
      >
        <template #header>
          <div style="display:flex;align-items:center;gap:10px;cursor:pointer" @click="go('/master/contracts')">
            <n-tag size="small" type="info">销售合同</n-tag>
            <span style="font-weight:600">{{ sc.contract_no || '未编号' }}</span>
            <span style="color:#64748B">{{ sc.party_name }}</span>
            <span class="num" style="color:#64748B">含税 {{ money(sc.amount_incl_tax || sc.amount) }}</span>
            <n-tag size="small" :type="statusTagType(sc.status) as any">{{ sc.status }}</n-tag>
          </div>
        </template>

        <!-- 销售订单（含对账单状态） -->
        <div style="margin-left:16px;margin-bottom:8px">
          <div style="font-size:12px;color:#94A3B8;margin-bottom:4px">销售订单（{{ sc.sales_orders.length }}）</div>
          <div v-if="sc.sales_orders.length === 0" style="color:#CBD5E1;font-size:13px">暂无</div>
          <div
            v-for="so in sc.sales_orders" :key="so.id"
            style="display:flex;align-items:center;gap:10px;padding:4px 0;cursor:pointer"
            @click="go('/orders', { tab: 'sales' })"
          >
            <n-tag v-if="so.is_batch" size="tiny" type="success">批次</n-tag>
            <span>{{ so.label }}</span>
            <span style="color:#94A3B8;font-size:12px">{{ so.quantity }} 台</span>
            <span v-if="so.is_batch" style="color:#94A3B8;font-size:12px">已挂 {{ so.device_count }} 台</span>
            <span class="num" style="color:#64748B;font-size:12px">月租 {{ money(so.total_monthly_rent) }}</span>
            <n-tag size="tiny" :type="statusTagType(so.status) as any">{{ so.status }}</n-tag>
            <n-tag
              v-for="cf in so.confirmations" :key="cf.id" size="tiny"
              :type="statusTagType(cf.status) as any"
              @click.stop="go('/confirmations')"
            >对账单 {{ cf.period_label }} {{ cf.status }}</n-tag>
          </div>
        </div>

        <!-- 发票（销售方向，期2 起开票即确认收入） -->
        <div v-if="sc.invoices && sc.invoices.length" style="margin-left:16px;margin-bottom:8px">
          <div style="font-size:12px;color:#94A3B8;margin-bottom:4px">发票（{{ sc.invoices.length }}）</div>
          <div
            v-for="iv in sc.invoices" :key="iv.id"
            style="display:flex;align-items:center;gap:10px;padding:4px 0;cursor:pointer"
            @click="go('/invoices')"
          >
            <span>{{ iv.invoice_no || '未编号' }}</span>
            <span class="num" style="color:#64748B;font-size:12px">含税 {{ money(iv.amount) }}</span>
            <n-tag size="tiny" :type="statusTagType(iv.status) as any">{{ iv.status }}</n-tag>
            <span v-if="iv.paid_date" style="color:#94A3B8;font-size:12px">回款 {{ iv.paid_date }}</span>
          </div>
        </div>

        <!-- 参照本销售合同的采购合同 -->
        <div style="margin-left:16px">
          <div style="font-size:12px;color:#94A3B8;margin-bottom:4px">
            采购合同（{{ sc.purchase_contracts.length }}，参照本销售合同）
          </div>
          <div v-if="sc.purchase_contracts.length === 0" style="color:#CBD5E1;font-size:13px">暂无</div>
          <div
            v-for="pc in sc.purchase_contracts" :key="pc.id"
            style="border:1px solid #F1F5F9;border-radius:6px;padding:8px 10px;margin-bottom:8px"
          >
            <div style="display:flex;align-items:center;gap:10px;cursor:pointer" @click="go('/master/contracts')">
              <n-tag size="small" type="warning">采购合同</n-tag>
              <span style="font-weight:600">{{ pc.contract_no || '未编号' }}</span>
              <span style="color:#64748B">{{ pc.party_name }}</span>
              <span class="num" style="color:#64748B">含税 {{ money(pc.amount_incl_tax || pc.amount) }}</span>
              <n-tag size="small" :type="statusTagType(pc.status) as any">{{ pc.status }}</n-tag>
            </div>

            <!-- 采购订单 + 预付款（批次汇总 / 单台穿透） -->
            <div style="margin-left:16px;margin-top:6px">
              <div v-if="pc.orders.length === 0" style="color:#CBD5E1;font-size:13px">暂无采购订单</div>
              <div v-for="o in pc.orders" :key="o.id" style="padding:4px 0">
                <div style="display:flex;align-items:center;gap:10px">
                  <span :data-testid="`toggle-devices-${o.id}`" style="cursor:pointer;display:inline-flex;align-items:center" @click="toggle(o.id)">
                    <chevron-down v-if="expanded[o.id]" :size="14" />
                    <chevron-right v-else :size="14" />
                  </span>
                  <n-tag v-if="o.is_batch" size="tiny" type="success">批次</n-tag>
                  <span style="cursor:pointer" @click="go('/orders', { tab: 'purchase' })">{{ o.label }}</span>
                  <span v-if="o.quantity" style="color:#94A3B8;font-size:12px">{{ o.quantity }} 台</span>
                  <span class="num" style="color:#64748B;font-size:12px">{{ money(o.total_amount) }}</span>
                  <n-tag size="tiny" :type="statusTagType(o.status) as any">{{ o.status }}</n-tag>
                  <n-tag size="tiny" :type="ppType(o.prepayment.status)">
                    预付款 {{ o.prepayment.status }}
                  </n-tag>
                  <span v-if="o.prepayment.total > 0" class="num" style="color:#94A3B8;font-size:12px">
                    {{ money(o.prepayment.settled) }} / {{ money(o.prepayment.total) }}
                  </span>
                </div>
                <!-- 单台穿透 -->
                <div v-if="expanded[o.id]" style="margin-left:30px;margin-top:4px">
                  <div v-if="o.devices.length === 0" style="color:#CBD5E1;font-size:12px">未挂载设备</div>
                  <div
                    v-for="d in o.devices" :key="d.id"
                    style="display:flex;align-items:center;gap:10px;padding:2px 0;font-size:12px;cursor:pointer"
                    @click="go('/devices')"
                  >
                    <span class="num" style="font-weight:600">{{ d.sn }}</span>
                    <n-tag size="tiny" :type="statusTagType(d.status) as any">{{ d.status }}</n-tag>
                    <span v-if="d.prepayment_amount > 0" class="num" style="color:#64748B">
                      预付 {{ money(d.prepayment_amount) }} · 已核销 {{ money(d.prepayment_settled_amount) }}
                    </span>
                    <n-tag v-if="d.prepayment_amount > 0" size="tiny"
                           :type="d.prepayment_settled ? 'success' : 'warning'">
                      {{ d.prepayment_settled ? '已回核销' : '已付挂账' }}
                    </n-tag>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </n-card>

      <!-- 历史孤儿数据：无参照的采购合同 / 未挂合同的订单 -->
      <n-card v-if="tree.orphan_purchase_contracts.length || tree.unlinked_orders.length"
              size="small" style="margin-bottom:12px;border-left:4px solid #D97706">
        <template #header><span style="font-weight:600">待补齐关联（历史数据）</span></template>
        <div v-for="pc in tree.orphan_purchase_contracts" :key="pc.id"
             style="display:flex;align-items:center;gap:10px;padding:4px 0;cursor:pointer"
             @click="go('/master/contracts')">
          <n-tag size="small" type="warning">采购合同·未参照</n-tag>
          <span>{{ pc.contract_no || '未编号' }}</span>
          <span style="color:#64748B">{{ pc.party_name }}</span>
          <n-tag size="small" :type="statusTagType(pc.status) as any">{{ pc.status }}</n-tag>
        </div>
        <div v-for="o in tree.unlinked_orders" :key="o.id"
             style="display:flex;align-items:center;gap:10px;padding:4px 0;cursor:pointer"
             @click="go('/orders', { tab: 'purchase' })">
          <n-tag size="small" type="default">订单·未挂合同</n-tag>
          <span>{{ o.label }}</span>
          <n-tag size="tiny" :type="ppType(o.prepayment.status)">预付款 {{ o.prepayment.status }}</n-tag>
        </div>
      </n-card>

      <n-empty
        v-if="!tree.sales_contracts.length && !tree.leasing_processes.length
              && !tree.orphan_purchase_contracts.length && !tree.unlinked_orders.length"
        description="暂无业务对象：先录入销售合同，再参照创建采购合同"
        style="padding:24px 0"
      />

      <!-- 发起金租申请（预填本项目） -->
      <n-modal v-model:show="showLease" preset="card" title="发起金租申请" style="width:440px;max-width:94vw">
        <n-form label-placement="left" :label-width="90">
          <n-form-item label="金租机构" required>
            <n-select v-model:value="leaseForm.supplier_id" :options="fundSuppliers" filterable
                      placeholder="选择资金供应商" data-testid="lease-supplier" />
          </n-form-item>
          <n-form-item label="申请金额" required>
            <n-input-number v-model:value="leaseForm.total_amount" :min="0" :show-button="false"
                            style="width:100%" placeholder="元" data-testid="lease-amount" />
          </n-form-item>
          <n-form-item label="年利率%">
            <n-input-number v-model:value="leaseForm.annual_rate" :min="0" :precision="2" style="width:100%" placeholder="如 4 = 4%" />
          </n-form-item>
          <n-form-item label="期数">
            <n-input-number v-model:value="leaseForm.term_periods" :min="1" style="width:100%" />
          </n-form-item>
          <n-form-item label="还款频率"><n-select v-model:value="leaseForm.payment_freq" :options="FREQ_OPTS" /></n-form-item>
          <n-form-item label="还款方式"><n-select v-model:value="leaseForm.repayment_method" :options="REPAY_OPTS" /></n-form-item>
        </n-form>
        <template #footer>
          <div style="display:flex;justify-content:flex-end;gap:8px">
            <n-button @click="showLease = false">取消</n-button>
            <n-button type="primary" data-testid="lease-submit" @click="submitLease">提交申请</n-button>
          </div>
        </template>
      </n-modal>
    </div>
  </n-spin>
</template>

<style scoped>
.num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>