<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import GenericCrud from '../components/GenericCrud.vue'
import { MODULES } from '../config/modules'

const route = useRoute()
const config = computed(() => MODULES[route.params.module as string])
</script>

<template>
  <GenericCrud v-if="config" :config="config" />
  <div v-else style="padding:24px;color:#888">未配置该模块</div>
</template>
