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
