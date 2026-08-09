import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,  // 全链路栈较慢（nginx→backend→db），30s 对重页面+截图不够
  // 走 nginx(8080) → backend(8000) → db 全链路，最接近真实用户路径
  use: { baseURL: 'http://localhost:8080' },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  reporter: [['list']],
  // 全套跑完清 dev-DB 本轮 e2e 数据，防共享库测试数据无限堆积（见 global-teardown.ts）。
  globalTeardown: './global-teardown',
})
