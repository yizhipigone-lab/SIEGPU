/**
 * 用 DSH 自己的 zstd 解压器读会话日志，定位 seq 断档。
 * 用法: node inspect-session.mjs <session.jsonl.zstd 路径>
 */
import { readFileSync } from 'node:fs'

const file = process.argv[2]
const buf = readFileSync(file)

// 用 DSH 的 zstd 工具（scanZstdFrames + decompressZstdFrame）
const dshZstd = 'file:///D:/Program Files/DSH/packages/session/session-persistence-jsonl/src/zstd.ts'
let scanZstdFrames, decompressZstdFrame
try {
  const m = await import(dshZstd)
  scanZstdFrames = m.scanZstdFrames
  decompressZstdFrame = m.decompressZstdFrame
} catch (e) {
  console.log('无法加载 DSH zstd 模块:', e.message)
  process.exit(2)
}

const scan = scanZstdFrames(buf)
const frames = scan.frames
console.log('总帧数:', frames.length, 'tornStart:', scan.tornStart)

// 解压所有帧拼出 JSONL 文本
const parts = []
for (const f of frames) {
  try {
    parts.push(await decompressZstdFrame(buf.subarray(f.start, f.end)))
  } catch (e) {
    console.log(`帧 ${f.start}-${f.end} 解压失败:`, e.message)
  }
}
const text = Buffer.concat(parts).toString('utf8')
const lines = text.split('\n').filter(l => l.trim())
console.log('总行数:', lines.length)

// 找 seq 断档
let prev = null
let gapCount = 0
for (let i = 0; i < lines.length; i++) {
  let seq = null
  try { seq = JSON.parse(lines[i]).seq } catch { /* 非事件行 */ }
  if (seq !== null && seq !== undefined) {
    if (prev !== null && seq !== prev + 1 && seq > prev) {
      console.log(`断档 @行${i + 1}: prev=${prev} -> seq=${seq} (差 ${seq - prev})`)
      gapCount++
      if (gapCount > 10) { console.log('...(更多断档省略)'); break }
    }
    prev = Math.max(prev ?? seq, seq)
  }
}
if (gapCount === 0) console.log('无 seq 断档（按 max(prev) 递增口径）')

// 看第 1568 行附近（报错说的位置）
console.log('\n=== 第 1565-1572 行原文 ===')
for (let i = 1564; i < Math.min(1572, lines.length); i++) {
  const s = lines[i]
  console.log(`行${i + 1}: ${s.slice(0, 150)}`)
}
