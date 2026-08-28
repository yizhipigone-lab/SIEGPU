<script setup lang="ts">
import type { GlobalThemeOverrides } from 'naive-ui'
import {
  NConfigProvider, NDialogProvider, NLoadingBarProvider, NMessageProvider,
  dateZhCN, zhCN,
} from 'naive-ui'
import { onMounted } from 'vue'
import { useMetaStore } from './stores/meta'

// 共享常量单一真源（架构 #5 薄版）：登录态下启动拉一次，失败回退本地兜底
const meta = useMetaStore()
onMounted(() => {
  if (localStorage.getItem('token')) meta.load()
})

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#B45309',
    primaryColorHover: '#92400E',
    primaryColorPressed: '#7C2D12',
    primaryColorSuppl: '#B45309',
    infoColor: '#2563EB',
    infoColorHover: '#1D4ED8',
    successColor: '#16A34A',
    successColorHover: '#15803D',
    warningColor: '#EA580C',
    warningColorHover: '#C2410C',
    errorColor: '#DC2626',
    errorColorHover: '#B91C1C',
    bodyColor: '#F5F7FA',
    textColorBase: '#0F172A',
    borderColor: '#E2E8F0',
    dividerColor: '#E2E8F0',
    borderRadius: '8px',
    borderRadiusSmall: '5px',
    fontFamily: "'Plus Jakarta Sans','Noto Sans SC',system-ui,sans-serif",
    fontFamilyMono: "'JetBrains Mono',ui-monospace,monospace",
    fontSize: '14px',
  },
  Card: { borderRadius: '14px', color: '#FFFFFF' },
  Button: { fontWeight: '500' },
  DataTable: { thColor: '#F8FAFC', thTextColor: '#475569', borderColor: '#E2E8F0' },
  Tag: { borderRadius: '5px' },
}
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <n-loading-bar-provider>
      <n-message-provider>
        <n-dialog-provider>
          <router-view />
        </n-dialog-provider>
      </n-message-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>
