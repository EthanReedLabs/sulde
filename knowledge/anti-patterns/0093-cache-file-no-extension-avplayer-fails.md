---
doc_id: "ap-0093"
container: anti-patterns
platform: cross
summary: "Cache 文件用 hash 命名无扩展名 → iOS AVPlayer 解码失败 -11828"
related: ["ap-0226"]
---

# 0093 — Cache 文件用 hash 命名无扩展名 → iOS AVPlayer 解码失败 -11828

- **平台**:iOS（主要）+ Android（差异行为，容忍但同源）
- **复发次数**:1
- **lint 状态**:⏳ pending（候选规则见末尾）

## 现象

iOS 媒体列表页所有视频卡只显 thumbnail，**video layer 不出帧**。加 AVPlayerItem.status KVO observe 实证:

```
[layer.kvo.itemStatus] id=X status=.failed err=AVError -11828
  "The operation could not be completed. (This media format is not supported.)"
```

Module 路径 100% 对（`handle.resume()` 调了 / state `.ready` / volume 计算对），问题在 AVPlayerItem 创建阶段 — file 加载失败。

## 根因

DiskCache 用 SHA256 hash 命名 cache 文件，**无扩展名**:

```swift
// ❌ 修前（broken on iOS 16.7+）
private func filePath(for url: URL) -> URL {
    directory.appendingPathComponent(sha256(url.absoluteString))
}
// 写盘 → /Library/Caches/.../a9fb99b067df...74f3  (无扩展名)
```

iOS `AVURLAsset` 按 **文件扩展名** 判 media type:
- 无扩展名 → `AVURLAsset` 无法识别 → `AVPlayerItem.status = .failed`（`AVError -11828`）
- `AVURLAssetTypeHintKey` 是 iOS 17+ API，**iOS 16.x 唯一稳定路径 = 文件名带扩展名**

### 为什么重构前 100% 工作

重构前 `AVPlayerItem(url: remoteUrl)`，remoteUrl path 自带 `.mp4` → AVURLAsset 识别 OK。重构后 cache 下载到本地 `<sha256>`（无后缀）→ AVURLAsset 识别失败。

## 修法

`filePath` 保留原 URL 扩展名，fallback `mp4`:

```swift
// ✅ 修后
private func filePath(for url: URL) -> URL {
    let hash = sha256(url.absoluteString)
    let ext = url.pathExtension
    let safeExt = ext.isEmpty ? "mp4" : ext
    return directory.appendingPathComponent(hash).appendingPathExtension(safeExt)
}
```

旧无后缀 cache 文件视为 cache miss，下次重新 download 写带 `.mp4` 路径;旧文件按 mtime LRU 自然清。

## Android 同源差异（为何 Android 不撞）

Android DiskCache 同样用 hash 命名（无扩展名），但 **ExoPlayer 容忍**:

- `MediaItem.fromUri(Uri.fromFile(source))` + `DefaultMediaSourceFactory` 含 `DefaultExtractorsFactory`
- ExtractorsFactory 内 9+ 个 extractor（MP4 / FLV / MP3 / OGG 等）轮流 **content sniff**（读 file header magic number）
- MP4 ftyp box 在前 ~32 bytes，Android 读到即识别 → 即使无扩展名仍能播

Android 可考虑**性能优化**:cache file 带扩展名 → ExoPlayer 直接走 MP4 extractor 无需 sniff（P3，可选）。

## 双端差异对照

| 端 | Player | 容忍无扩展名? | 真机症状 |
|---|---|---|---|
| **iOS 16.7+** | `AVPlayer + AVURLAsset` | ❌ `AVError -11828` 即刻失败 | 视频完全不播 |
| **iOS 17+** | 可加 `AVURLAssetTypeHintKey` | ⚠️ 仅显式 hint 才容忍 | 同 16.x（若 caller 未传 hint） |
| **Android Media3 ExoPlayer** | `DefaultExtractorsFactory` content sniff | ✅ 自动 sniff MP4 | 视频正常播（可能慢一拍） |

## Lint 候选

```bash
# iOS:grep media/video cache feature 内 appendingPathComponent 后无 appendingPathExtension
grep -rn "appendingPathComponent" Sources/ | while read line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    if ! sed -n "${lineno},+3p" "$file" | grep -q "appendingPathExtension\|pathExtension"; then
        echo "⚠️ $file:$lineno appendingPathComponent 无后续 PathExtension"
    fi
done
# Android:grep Uri.fromFile / MediaItem.fromUri 前 5 行内是否含 mimeType / withMimeType
```

## 协调端反省（多轮 hypothesis 失败的教训）

iOS 4 轮 hypothesis 失败:
1. setMuted/setVisibility race condition
2. SwiftUI LazyVStack `.onDisappear` 时机滞后
3. AVAudioSession `.soloAmbient`
4. SwiftUI Button hit-test 被外层 onTapGesture 截获

**协调端凭 grep + 推断派 fix，Dev 严格按 hypothesis 实施 → 4 次失败**。第 5 轮 Dev 自发加 **AVPlayerItem.status KVO observe + dump file header 32 bytes** 实证驱动，5min 内定位真因。

**永久铁律**:
- 协调端 audit 推 root cause 前，**必先让 Dev 加 runtime probe**（iOS:KVO `currentItem.status / .timeControlStatus`;Android:`Player.Listener.onPlayerError / onPlaybackStateChanged`）
- 不要凭 grep + 推断"嫌疑"派 fix task md
- systematic-debugging 的 evidence gathering **必先于** hypothesis testing
- task md root cause 字段写"嫌疑"（留 escalation 路径），避免 Dev 严格按 hypothesis 写 fix 无验证机制

## 关联

- 每次 new player（Player 池 + cache file 是 Module 双柱契约）
