/**
 * 用 esbuild 把 src/client 打包成 DSH client 插件格式：
 * window.__ModuleLoader__.load({ id, factory })。
 * 参照 dshmarket 的 tsdown + normalize-client-banner 产物形态。
 */
import { writeFileSync, mkdirSync, readFileSync, unlinkSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'

const root = dirname(dirname(fileURLToPath(import.meta.url)))

/**
 * 解析 esbuild：优先 ESM `import('esbuild')`（在 DSH 工作区运行时命中），
 * 失败则回退到 DSH 工作区的 pnpm hoisted store（esbuild 经 junction 暴露在
 * node_modules/.pnpm/node_modules/esbuild），用 createRequire 解析。
 */
async function loadEsbuild() {
  try {
    return await import('esbuild')
  } catch {
    const DSH_ROOT = process.env.DSH_ROOT ?? dirname(dirname(process.execPath))
    const req = createRequire(join(DSH_ROOT, 'node_modules', '.pnpm', 'node_modules', '__noop__.js'))
    return req('esbuild')
  }
}

const esbuild = await loadEsbuild()
const build = esbuild.build ?? esbuild.default?.build

const result = await build({
  entryPoints: [join(root, 'src/client/index.tsx')],
  bundle: true,
  format: 'iife',
  platform: 'browser',
  jsx: 'automatic',
  external: ['react', 'react/jsx-runtime'],
  outfile: join(root, 'lib/_client_raw.js'),
  write: true,
  logLevel: 'silent',
})

const raw = readFileSync(join(root, 'lib/_client_raw.js'), 'utf8')
const banner = `window.__ModuleLoader__.load({
  id: "dsh-live-ticker",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
${raw.split('\n').map((l) => '    ' + l).join('\n')}
    return module.exports;
  }
});
`
mkdirSync(join(root, 'lib'), { recursive: true })
writeFileSync(join(root, 'lib/client.js'), banner)
// 清理中间产物
unlinkSync(join(root, 'lib/_client_raw.js'))
console.log('built lib/client.js', banner.length, 'bytes')
