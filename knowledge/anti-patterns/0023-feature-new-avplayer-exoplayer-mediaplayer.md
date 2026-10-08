---
doc_id: "ap-0023"
container: anti-patterns
platform: cross
summary: "Feature 模块自建 AVPlayer / ExoPlayer / MediaPlayer 实例"
---

# 0023 — Feature 模块自建 AVPlayer / ExoPlayer / MediaPlayer 实例

- **平台**:iOS + Android（同源）
- **复发次数**:0（脚手架已建，防未然）
- **lint 状态**:双端 ⏳ 思路就绪

## ❌ 错误（iOS）

```swift
// Feature 模块直接 new AVPlayer
struct ClipDialogView: View {
    @State private var player = AVPlayer()             // ← Feature 直接 new
    var body: some View {
        VideoPlayer(player: player)
            .onAppear { player.replaceCurrentItem(...) }
    }
}
```

## ❌ 错误（Android）

```kotlin
// Feature 模块直接 new ExoPlayer
class ClipFragment : Fragment() {
    private val exoPlayer by lazy {                    // ← Feature 直接 new
        ExoPlayer.Builder(requireContext()).build()
    }
}
```

## 为什么错

- 多页同时持有不同播放器实例 → 双声播放（用户切换时旧实例还在响）
- 后台 / 锁屏 / 来电中断各页各自处理 AVAudioSession / AudioFocus → 互相覆盖
- range 循环 / 切换 / interruption 等共享逻辑各自实现 → bug 滋生
- 违反"CoreUI 提供脚手架，Feature 只消费"分层

## ✅ 正确

```swift
// iOS — 任何 Feature 都通过 CoreUI 单例
import CoreUI
AudioPreviewPool.shared.play(trackId: id, url: url, range: range)
AudioPreviewPool.shared.pause()
AudioPreviewPool.shared.statePublisher  // 订阅播放态
```

```kotlin
// Android
AudioPreviewPool.shared.play(trackId, url, range)
AudioPreviewPool.shared.pause()
AudioPreviewPool.shared.state.collect { ... }
```

CoreUI 内置：单例 + AVAudioSession / AudioFocus 抢占 + 后台 pause + interruption pause + range 循环 + 切换停旧。

## lint 状态

- iOS: ⏳ `grep 'AVPlayer('` 排除 CoreUI 音频脚手架目录，Feature 模块出现 = 违规
- Android: ⏳ `grep 'MediaPlayer\b\|ExoPlayer\.Builder'` 排除 CoreUI 音频脚手架目录，Feature 出现 = 违规

## 预防

新 Feature 任何时候要播音频 / 视频 → **第一反应是去 CoreUI 找单例**，而非自己 new。CoreUI 没有的能力（如 4K HDR 播放器）应**派 CoreUI 任务**而非 Feature 私自实现。

## 关联

- 框架脚手架规范 AudioPreviewPool 段
- 反模式 0026（池化复用后的 setPlayer 陷阱，是本条之后的下一层坑）
