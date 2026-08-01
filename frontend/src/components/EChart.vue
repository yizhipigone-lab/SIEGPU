<script setup lang="ts">
import VChart from 'vue-echarts'
import { registerTheme } from 'echarts/core'
import 'echarts'  // 全量注册所有图表/组件

registerTheme('siegpu', {
  color: ['#B45309', '#0F766E', '#2563EB', '#7C3AED', '#DC2626', '#16A34A', '#EA580C', '#64748B'],
  backgroundColor: 'transparent',
  textStyle: { fontFamily: 'Plus Jakarta Sans, Noto Sans SC, sans-serif', color: '#0F172A' },
  title: { textStyle: { color: '#0F172A', fontWeight: 600 }, subtextStyle: { color: '#64748B' } },
  legend: { textStyle: { color: '#475569' } },
  tooltip: {
    backgroundColor: '#FFFFFF', borderColor: '#E2E8F0', borderWidth: 1,
    textStyle: { color: '#0F172A' }, extraCssText: 'box-shadow: 0 4px 16px rgba(15,23,42,.12); border-radius:10px;',
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: '#CBD5E1' } },
    axisTick: { show: false },
    axisLabel: { color: '#64748B' },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#64748B' },
    splitLine: { lineStyle: { color: '#EEF2F6' } },
  },
})

defineProps<{ option: Record<string, any>; height?: string }>()
</script>

<template>
  <v-chart class="echart" :option="option" theme="siegpu" autoresize :style="{ height: height || '300px' }" />
</template>

<style scoped>
.echart { width: 100%; }
</style>
