/**
 * 修复会话日志的 seq 断档：把所有事件重排为从 0 开始的严格连续序号。
 * 打包行（*-chunks）重写 seq0 为当前序号（展开后仍连续）；普通事件重写 seq。
 * 保留每行的其他字段不动。用 DSH 的 zstd 帧格式写回。
 *
 * 用法: node repair-session.mjs <session.jsonl.zstd>
 * 会先写 <file>.bak 备份原文件，再原地写回修复后的文件。
 */
import { readFileSync, writeFileSync, copyFileSync } from 'node:fs'

const file = process.argv[2]
if (!file) { console.error('usage: node repair-session.mjs <session.jsonl.zstd>'); process.exit(2) }

const dshZstd = 'file:///D:/Program Files/DSH/packages/session/session-persistence-jsonl/src/zstd.ts'
const { scanZstdFrames, decompressZstdFrame, compressZstdFrame } = await import(dshZstd)

const buf = readFileSync(file)
const { frames } = scanZstdFrames(buf)

// 解压全部帧拼出文本
const parts = []
for (const f of frames) {
  parts.push(await decompressZstdFrame(buf.subarray(f.start, f.end)))
}
const text = Buffer.concat(parts).toString('utf8')
const lines = text.split('\n')

// 第一行是 header（无 seq），保留不动
const header = lines[0]
const eventLines = lines.slice(1).filter(l => l.trim().length > 0)

const CHUNK_TAGS = new Set(['text-chunks', 'reasoning-chunks', 'tool-call-chunks'])

let nextSeq = 0
let fixed = 0
const out = [header]
for (const line of eventLines) {
  let rec
  try { rec = JSON.parse(line) } catch { continue } // 丢弃不可解析行
  if (rec && typeof rec === 'object' && typeof rec.type === 'string') {
    if (CHUNK_TAGS.has(rec.type) && typeof rec.seq0 === 'number') {
      // 打包行：重写 seq0 为当前序号（展开后 members.length 个事件 seq0..seq0+len-1 连续）
      const members = rec.type === 'tool-call-chunks' ? rec.data?.args : rec.data?.texts
      const len = Array.isArray(members) ? members.length : 0
      if (rec.seq0 !== nextSeq) { rec.seq0 = nextSeq; fixed++ }
      nextSeq += len
    } else if (typeof rec.seq === 'number') {
      // 普通事件：重写 seq 为当前序号
      if (rec.seq !== nextSeq) { rec.seq = nextSeq; fixed++ }
      nextSeq += 1
    }
    // 无 seq 的行（如 header 类）原样保留
  }
  out.push(JSON.stringify(rec))
}

const newText = out.join('\n') + '\n'

// 用 DSH 的 zstd 帧压缩写回（一帧装全部内容；DSH 的 scanZstdFrames 支持多帧，单帧也合法）
const compressed = await compressZstdFrame(Buffer.from(newText, 'utf8'))

// 备份原文件再写回
copyFileSync(file, file + '.bak')
writeFileSync(file, compressed)

console.log('事件行数:', eventLines.length)
console.log('重编 seq 的行数:', fixed)
console.log('最终 seq 总数:', nextSeq)
console.log('备份:', file + '.bak')
console.log('已写回:', file, `(${compressed.length} bytes)`)
