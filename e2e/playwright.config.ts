import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  // 走 nginx(8080) → backend(8000) → db 全链路，最接近真实用户路径
  use: { baseURL: 'http://localhost:8080' },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  reporter: [['list']],
})
