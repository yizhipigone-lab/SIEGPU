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
- 用 `compressZstdFrame` 重新压缩写回

`verify-session.mjs` 用 DSH 的 `scanLog` 验证修复结果。

`inspect-session.mjs` 用于诊断：列出所有断档位置和指定行附近原文。

## 注意事项

- 修复后该会话的 seq 与原始写入时不再一致，但内容完整、可正常加载展示。
- 确认会话能正常打开后，可删除 `.bak` 备份。
- 如果只有"中断那一个会话"报错、其他会话正常，说明是单会话损坏；批量出现则可能是系统性问题，需另查。
