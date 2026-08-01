<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NForm, NFormItem, NInput, NIcon, useMessage } from 'naive-ui'
import { Lock, User } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()
const username = ref('')
const password = ref('')
const loading = ref(false)
const isDev = import.meta.env.DEV

async function onSubmit() {
  if (!username.value || !password.value) { message.warning('请输入账号和密码'); return }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.push('/')
  } catch {
    message.error('登录失败：用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="brand-row">
        <div class="logo">S</div>
        <div>
          <div class="title">SIEGPU ERP</div>
          <div class="subtitle">算力租赁 · 资金 / 金租 / 对账管理</div>
        </div>
      </div>

      <n-form @keyup.enter="onSubmit" style="margin-top:24px">
        <n-form-item label="账号" :show-feedback="false">
          <n-input v-model:value="username" placeholder="请输入账号" size="large">
            <template #prefix><n-icon :component="User" /></template>
          </n-input>
        </n-form-item>
        <n-form-item label="密码" :show-feedback="false" style="margin-top:12px">
          <n-input v-model:value="password" type="password" show-password-on="click" placeholder="请输入密码" size="large">
            <template #prefix><n-icon :component="Lock" /></template>
          </n-input>
        </n-form-item>
        <n-button type="primary" block size="large" :loading="loading" style="margin-top:20px" @click="onSubmit">
          登 录
        </n-button>
      </n-form>

      <p v-if="isDev" class="hint">开发种子账号（密码均为 sie123）：admin · cfo · buyer · delivery · finance</p>
    </div>
    <div class="foot">© 2026 SIEGPU · 内部系统</div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  background: radial-gradient(1200px 600px at 80% -10%, #FEF3C7 0%, transparent 60%),
              radial-gradient(900px 500px at -10% 110%, #E0F2FE 0%, transparent 55%),
              var(--c-bg);
}
.login-card {
  width: 380px; padding: 32px;
  background: var(--c-surface); border: 1px solid var(--c-border);
  border-radius: 18px; box-shadow: var(--sh-pop);
}
.brand-row { display: flex; align-items: center; gap: 12px; }
.logo {
  width: 44px; height: 44px; border-radius: 12px; flex: none;
  background: linear-gradient(135deg, var(--c-primary), var(--c-primary-pressed));
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-family: var(--font-heading); font-weight: 700; font-size: 22px;
  box-shadow: 0 6px 16px rgba(180,83,9,.35);
}
.title { font-family: var(--font-heading); font-size: 20px; font-weight: 700; color: var(--c-text); }
.subtitle { font-size: 12px; color: var(--c-text-2); margin-top: 2px; }
.hint { color: var(--c-text-3); font-size: 12px; margin-top: 16px; text-align: center; }
.foot { color: var(--c-text-3); font-size: 12px; margin-top: 24px; }
</style>
