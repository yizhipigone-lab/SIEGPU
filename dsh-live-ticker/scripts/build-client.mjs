/**
 * 用 esbuild 把 src/client 打包成 DSH client 插件格式：
 * window.__ModuleLoader__.load({ id, factory })。
 * 参照 dshmarket 的 tsdown + normalize-client-banner 产物形态。
 */
import { writeFileSync, mkdirSync, readFileSync, unlinkSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'
import vm from 'node:vm'

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
  // CJS 而非 IIFE：esbuild 会产出 `module.exports = __toCommonJS(...)` 并带
  // `exports.name / exports.apply / exports.inject` 赋值，命中 banner 里的
  // `module` 变量；external 变为 `require("react")`，绑定到 factory 的 require 参数。
  format: 'cjs',
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

// ---- loader-simulation self-check ----
// 真实执行产物，模拟 DSH 模块加载器，断言 name/apply/inject 都活了下来。
const code = readFileSync(join(root, 'lib/client.js'), 'utf8')
const sandbox = { window: {}, console, setTimeout, clearTimeout }
sandbox.window.__ModuleLoader__ = { load(def) { sandbox.__def = def } }
vm.runInNewContext(code, sandbox)
const factory = sandbox.__def.factory

// react / react/jsx-runtime 是 external：工厂运行时 require 它们。插件目录没有
// 本地 node_modules，createRequire 解不到；用 require shim 兜底返回最小 React
// stub（自检只需模块加载成功并检查导出键，React 内部无关紧要）。
const reactStub = { createElement: () => null, Fragment: Symbol('Fragment') }
const jsxRuntimeStub = { jsx: () => null, jsxs: () => null, Fragment: Symbol('Fragment') }
const stubById = { 'react': reactStub, 'react/jsx-runtime': jsxRuntimeStub }
const req = createRequire(join(root, 'noop.js'))
function resolveModule(id) {
  if (stubById[id]) return stubById[id]
  try { return req(id) } catch { return {} }
}
const mod = factory(resolveModule)
if (mod.name !== 'dsh-live-ticker' || typeof mod.apply !== 'function' || !Array.isArray(mod.inject) || !mod.inject.includes('slots')) {
  throw new Error(`loader self-check failed: got ${JSON.stringify({ name: mod.name, apply: typeof mod.apply, inject: mod.inject })}`)
}
console.log('loader self-check OK:', mod.name, mod.inject.join(','))

// 清理中间产物
unlinkSync(join(root, 'lib/_client_raw.js'))
console.log('built lib/client.js', Buffer.byteLength(code), 'bytes')
