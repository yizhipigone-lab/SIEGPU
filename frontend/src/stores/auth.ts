import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { Token } from '../types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const role = ref<string | null>(localStorage.getItem('role'))
  const displayName = ref<string | null>(localStorage.getItem('displayName'))

  async function login(username: string, password: string) {
    const { data } = await api.post<Token>('/auth/login', new URLSearchParams({ username, password }))
    token.value = data.access_token
    role.value = data.role
    displayName.value = data.display_name ?? null
    localStorage.setItem('token', data.access_token)
    localStorage.setItem('role', data.role)
    if (data.display_name) localStorage.setItem('displayName', data.display_name)
    // 登录成功即拉共享常量（不 await 结果；chunk 加载/接口失败都走本地兜底，不影响登录）
    try {
      const { useMetaStore } = await import('./meta')
      useMetaStore().load()
    } catch { /* 常量拉取失败无害：meta store 自带本地兜底 */ }
  }

  function logout() {
    token.value = null
    role.value = null
    displayName.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('role')
    localStorage.removeItem('displayName')
  }

  return { token, role, displayName, login, logout }
})
