/**
 * 验证修复后的会话日志能被 DSH 正常加载。
 * 两层校验，与启动器的真实加载路径同口径：
 *   1) 装帧层：第一帧解压后必须恰好是一行 header（readFirstZstdLine / assertZstdHeaderFrame）
 *   2) 内容层：事件 seq 严格连续（scanLog）
 * 用法: node verify-session.mjs <session.jsonl.zstd>
 */
import { readFileSync } from 'node:fs'

const file = process.argv[2]
const buf = readFileSync(file)

const dshZstd = 'file:///D:/Program Files/DSH/packages/session/session-persistence-jsonl/lib/types/zstd.js'
const dshFormat = 'file:///D:/Program Files/DSH/packages/session/session-persistence-jsonl/lib/types/format.js'
const { scanZstdFrames, decompressZstdFrame } = await import(dshZstd)
const { scanLog } = await import(dshFormat)

const { frames } = scanZstdFrames(buf)

// 第一层：装帧校验（启动器同口径）——第一帧必须恰好一行 header
if (frames.length === 0) {
  console.log('❌ 装帧损坏: 无任何 zstd 帧')
  process.exit(1)
}
const first = frames[0]
const firstPlain = await decompressZstdFrame(buf.subarray(first.start, first.end))
const isHeaderOnly = firstPlain.length > 0 && firstPlain.indexOf(0x0A) === firstPlain.length - 1
if (!isHeaderOnly) {
  console.log('❌ 装帧损坏: 第一帧不是恰好一行 header（启动器 readFirstZstdLine 会拒绝）')
  console.log('   第一帧解压后', firstPlain.length, '字节；合法应为几百字节的一行')
  process.exit(1)
}
console.log('✅ 装帧合法: 第一帧为单行 header（', firstPlain.length, '字节）')

// 第二层：内容校验（seq 连续性）
const parts = []
for (const f of frames) {
  parts.push(await decompressZstdFrame(buf.subarray(f.start, f.end)))
}
const text = Buffer.concat(parts)

try {
  const scan = scanLog(text)
  console.log('✅ 内容合法: 无 seq gap')
  console.log('事件数:', scan.events.length)
  console.log('meta.id:', scan.meta?.id)
} catch (e) {
  console.log('❌ 内容损坏:', e.message)
  process.exit(1)
}
