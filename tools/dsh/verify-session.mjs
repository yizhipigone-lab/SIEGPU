/**
 * 验证修复后的会话日志能被 DSH 扫描器正常读取（无 seq gap）。
 * 用法: node verify-session.mjs <session.jsonl.zstd>
 */
import { readFileSync } from 'node:fs'

const file = process.argv[2]
const buf = readFileSync(file)

const dshZstd = 'file:///D:/Program Files/DSH/packages/session/session-persistence-jsonl/src/zstd.ts'
const dshFormat = 'file:///D:/Program Files/DSH/packages/session/session-persistence-jsonl/src/format.ts'
const { scanZstdFrames, decompressZstdFrame } = await import(dshZstd)
const { scanLog } = await import(dshFormat)

const { frames } = scanZstdFrames(buf)
const parts = []
for (const f of frames) {
  parts.push(await decompressZstdFrame(buf.subarray(f.start, f.end)))
}
const text = Buffer.concat(parts)

try {
  const scan = scanLog(text)
  console.log('✅ 扫描成功，无 seq gap')
  console.log('事件数:', scan.events.length)
  console.log('meta.id:', scan.meta?.id)
  console.log('committedBytes:', scan.committedBytes)
} catch (e) {
  console.log('❌ 扫描失败:', e.message)
  process.exit(1)
}
