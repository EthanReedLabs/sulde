---
doc_id: "ap-0128"
container: anti-patterns
platform: ios
summary: "0128 iOS 自定义播放器漏 STATE_ENDED → seekTo(0) → 视频「只能播一次」"
---

# 0128 iOS 自定义播放器漏 STATE_ENDED → seekTo(0) → 视频「只能播一次」

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

AVKit `VideoPlayer`(系统控件)自带 replay,播完点 Replay 系统自帮 `seekTo(0)`。但**自定义 `AVPlayerLayer` + 自绘控制条**设 `actionAtItemEnd = .pause` 停末帧,且**无 `.AVPlayerItemDidPlayToEndTime` 观察器**:

```swift
// ❌ 自定义播放器:设 .pause 防自动循环,但无 end 观察器
loadItem { actionAtItemEnd = .pause }
func togglePlay() { player.play() }   // 末帧 currentTime==duration → play() no-op
```

结果:用户播完点 ▶ → 卡末帧 + 无声 + 无反馈,体感"只能播一次"。

## 为什么错

AVPlayer 在 `currentTime == duration` 时 `play()` 是 no-op(spec 行为),除非先 `seek(to: .zero)`。系统 AVKit 自动处理,自定义播放器 Dev 漏。同文件其他段已踩过同坑(用循环 seek 解),换自定义播放器时漏掉同款防护。

## ✅ 正确

```swift
// 加 STATE_ENDED 观察器
.onReceive(NotificationCenter.default.publisher(for: .AVPlayerItemDidPlayToEndTime)) { note in
    guard !store.isFullscreenPresented else { return }   // 全屏期交给系统 replay,内联不抢
    guard let item = note.object as? AVPlayerItem, item == player.currentItem else { return }
    player.seek(to: .zero); player.pause()   // 回首帧 = 恢复封面观感(循环则 .play)
}

// togglePlay 加固
func togglePlay() {
    if isAtEnd(player) { player.seek(to: .zero) }   // 防末帧 play() 无效
    if player.timeControlStatus == .playing { player.pause() } else { player.play() }
}
```

| 场景 | 命中 | 防护 |
|---|:-:|---|
| AVKit `VideoPlayer`(系统控件)| ❌ | 系统自动 replay |
| `AVPlayerLayer` + 自绘控制条 | ✅ | 必加 end 观察器 + togglePlay 末帧 seek |
| `AVPlayerViewController` 全屏 | ❌ | 内联 SwiftUI host 需 `isFullscreenPresented` guard 防双源抢 replay |
| 循环播放 | ✅ 反向 | `actionAtItemEnd = .none` + observer 内 `seek(.zero) + play()` |

## lint 状态

❓ 仅人工 checklist(end 事件是 runtime NotificationCenter publisher,静态 grep 抓不到漏写的观察器)。可加 soft 警告:grep `actionAtItemEnd = .pause` 命中点,同文件 ±100 行无 `.AVPlayerItemDidPlayToEndTime` → 警告。checklist:`.pause` 是否配套 end 观察器?observer 做 seek(.zero)+pause/play?togglePlay 末帧防护?全屏/内联双源 guard?

## 关联

- 异步渲染期遮罩(本反模式是后续播放期同源坑)
