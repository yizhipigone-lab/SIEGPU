<script setup lang="ts">
/**
 * 通用空状态：图标 + 文案 + 可选 CTA 按钮。
 * 用于各独立视图的 <n-data-table #empty>（GenericCrud 自带空状态，不用此组件）。
 * CTA 二选一：给了 ctaRoute 走路由跳转；否则 emit('action') 由父组件处理（如打开新增弹窗）。
 */
import { useRouter } from 'vue-router'
import { NButton, NEmpty } from 'naive-ui'

const props = defineProps<{
  description?: string
  ctaLabel?: string
  ctaRoute?: string
}>()
const emit = defineEmits<{ (e: 'action'): void }>()
const router = useRouter()

function onClick() {
  if (props.ctaRoute) router.push(props.ctaRoute)
  else emit('action')
}
</script>

<template>
  <n-empty :description="description || '暂无数据'" style="padding:32px 0">
    <template v-if="ctaLabel" #extra>
      <n-button size="small" type="primary" @click="onClick">{{ ctaLabel }}</n-button>
    </template>
  </n-empty>
</template>
