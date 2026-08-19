<script setup lang="ts">
// 千分位数字输入（金额/大数友好）：失焦显示 1,227,033,962.00；聚焦还原为原始数字便于编辑。
// v-model 仍是 number|null（与 NInputNumber 兼容），仅供 type:'number' 字段使用。
import { ref, watch } from 'vue'
import { NInput } from 'naive-ui'

const props = defineProps<{ value: number | null; placeholder?: string; status?: 'error' | 'warning' }>()
const emit = defineEmits<{ (e: 'update:value', v: number | null): void }>()

const focused = ref(false)
const text = ref('')

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return ''
  const neg = n < 0
  const [int, dec] = String(Math.abs(n)).split('.')
  const intFmt = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return (neg ? '-' : '') + intFmt + (dec !== undefined ? '.' + dec : '')
}
function parse(s: string): number | null {
  const clean = s.replace(/[,\s]/g, '')
  if (clean === '' || clean === '-' || clean === '.' || clean === '-.') return null
  const n = Number(clean)
  return Number.isNaN(n) ? null : n
}

// 外部值变化且非聚焦时刷新为格式化文本（编辑回填/自动计算都会走到这里）
watch(() => props.value, (v) => { if (!focused.value) text.value = fmt(v) }, { immediate: true })

function onFocus() {
  focused.value = true
  text.value = props.value === null || props.value === undefined ? '' : String(props.value)
}
function onBlur() {
  focused.value = false
  text.value = fmt(props.value)
}
function onInput(s: string) {
  text.value = s
  emit('update:value', parse(s))
}
</script>

<template>
  <n-input
    :value="text" :placeholder="placeholder" :status="status" inputmode="decimal"
    @update:value="onInput" @focus="onFocus" @blur="onBlur"
  />
</template>
