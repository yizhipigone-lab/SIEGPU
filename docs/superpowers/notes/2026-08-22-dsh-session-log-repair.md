# DSH 会话日志 seq 断档修复

> 日期：2026-08-22 · 场景：DSH（DeepSeek Harness）Web GUI
> 脚本：`tools/dsh/repair-session.mjs`、`tools/dsh/verify-session.mjs`、`tools/dsh/inspect-session.mjs`

## 症状

打开某个会话时报错：

```
历史加载失败：history unavailable for session "...": Error: corrupt session log:
seq gap in committed region at line N (expected X, got Y) (internal)
```

任何设备打开该会话都会报同样的错（与移动端/polyfill 无关）。

## 根因

DSH 会话日志（`~/.dsh/sessions/<工作区>/<session-id>/session.jsonl.zstd`）是 zstd 压缩的 JSONL，事件带严格连续的 `seq` 序号（从 0 开始）。当一次生成被**中断**（`turn/end` 的 `reason: interrupted`）时，写入器恢复后会从断点重新写，导致后续事件序号**回退**（例如 19426/19427 之后又出现 19425）。

DSH 的读取扫描器（`session-persistence-jsonl/src/format.ts` 的 `SessionLogScanner`）要求 committed 区域 seq 严格连续——发现回退就判定损坏并**拒绝加载整个历史**（防损坏设计，宁可不显示）。

日志物理上没坏（能解压、内容完整），只是序号连续性被中断打破。

## 修复方法

重排所有事件的 seq 为从 0 开始的严格连续序号，用 DSH 自己的 zstd 帧格式写回。

**用法**（在 `D:\Program Files\DSH` 目录下运行，用其自带 node）：

```powershell
# 1. 先备份由脚本自动完成（写 <file>.bak）
# 2. 修复
& 'D:\Program Files\DSH\.node\node.exe' --import tsx "tools/dsh/repair-session.mjs" "C:\Users\<你>\.dsh\sessions\<工作区>\<session-id>\session.jsonl.zstd"

# 3. 验证（用 DSH 扫描器确认无断档）
& 'D:\Program Files\DSH\.node\node.exe' --import tsx "tools/dsh/verify-session.mjs" "<同上路径>"
```

`repair-session.mjs` 会：
- 解压全部 zstd 帧为 JSONL
- 逐行重排 seq（打包行 `*-chunks` 重写 seq0 保持展开后连续；普通事件重写 seq）
- 自动备份原文件为 `.bak`
- 按产品格式写回：**header 单独一帧 + 事件体一帧**（`compressZstdFrame(header)` + `compressZstdFrame(body)`，参照 `encodeMaterialization`）

`verify-session.mjs` 两层验证（与启动器真实加载路径同口径）：装帧层（第一帧必须恰好一行 header）+ 内容层（seq 连续，用 `scanLog`）。

`inspect-session.mjs` 用于诊断：列出所有断档位置和指定行附近原文。

## 注意事项

- 修复后该会话的 seq 与原始写入时不再一致，但内容完整、可正常加载展示。
- 确认会话能正常打开后，可删除 `.bak` 备份。
- 如果只有"中断那一个会话"报错、其他会话正常，说明是单会话损坏；批量出现则可能是系统性问题，需另查。

## ⚠️ 血泪教训：装帧格式（2026-08-22 深夜补记）

**本脚本第一版写错了一次，导致 DSH 启动崩溃。** 教训必须记住：

DSH 会话日志的 zstd **装帧格式**有严格要求：**第一帧只能装一行 header**（`assertZstdHeaderFrame`），事件内容放后续帧。第一版 repair 脚本图省事把整个文件压成**单个帧**，启动器 `readFirstZstdLine` 一校验就拒：系统起不来。

三条铁律（适用于一切"程序启动时严格校验的持久化文件"）：

1. **修数据文件前，先读产品的写入代码**（不只是逻辑格式，还有物理装帧）。DSH 的正确写法在 `encodeMaterialization`：header 帧 + body 帧分开压。
2. **验证必须用真实的加载路径**。第一版的 verify 脚本用 `scanLog`（内容层）验证通过，但启动器走 `readFirstZstdLine`（装帧层）——内容合法 ≠ 装帧合法，那次是假绿。验证必须覆盖产品实际校验的每一层。
3. **不自创格式**。拿不准就用产品自带的写入/修复原语，别自己发明打包方式。

第二版已修正：repair 按双帧装帧写回，verify 增加装帧层校验（与启动器同口径），并实测过"好文件过 / 坏文件抓"两个方向。
