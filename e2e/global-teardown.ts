/**
 * 全套 e2e 跑完后，清理 dev-DB 本轮造的 e2e 测试数据，防共享库数据无限堆积。
 *
 * 历史教训（2026-08-09 一期终审）：e2e 无测试隔离，造的数据长期不清，堆出 99 条「采购待办」
 * 工作流 → get_my_tasks 无 LIMIT 全量加载 → 全量并发下请求超时被前端吞成空列表
 * （Dashboard.vue: myTasks.value = t.data || []）→ wizard-workspace a1 看到空待办卡 → 全套 flake。
 *
 * 判据在 backend/app/scripts/cleanup_e2e.py（按 E2E-/DC-/DBG- 等前缀，保留手工 demo 数据）。
 * 与 w9_final_audit.spec.ts 的 F1 同款 ``docker compose exec -T backend python`` 调用方式。
 *
 * 注意：e2e/package.json 无 "type":"module"，CommonJS，``__dirname`` 可用。
 *       docker-compose.yml 在仓库根，e2e/ 上一级即仓库根。
 */
import { execSync } from 'child_process'
import * as path from 'path'

export default async function globalTeardown(): Promise<void> {
  const repo = path.resolve(__dirname, '..') // e2e/ → 仓库根（docker-compose.yml 所在）
  try {
    execSync('docker compose exec -T backend python -m app.scripts.cleanup_e2e', {
      cwd: repo,
      stdio: ['ignore', 'inherit', 'inherit'],
    })
  } catch (e) {
    // 清理是「尽力而为」：不应让整个 e2e run 报红。只打印告警，便于发现脚本/容器异常。
    console.error('[global-teardown] cleanup_e2e 失败（不阻断 e2e 结果）：', (e as Error).message)
  }
}
