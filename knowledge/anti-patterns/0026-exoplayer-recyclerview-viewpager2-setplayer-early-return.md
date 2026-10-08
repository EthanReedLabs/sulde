---
doc_id: "ap-0026"
container: anti-patterns
platform: cross
summary: "ExoPlayer 池复用 + RecyclerView/ViewPager2 复用 → 同实例 setPlayer…"
---

# 0026 — ExoPlayer 池复用 + RecyclerView/ViewPager2 复用 → 同实例 setPlayer early return → 黑屏

- **平台**:Android（确认）；iOS 未池化未触发，池化前需回看
- **复发次数**:3
- **lint 状态**:Android ✅ grep 规则；iOS N/A

## 症状

短视频信息流（ViewPager2 / RecyclerView）用 N 实例 player 池，用户划走再回到原位置时**声音正常但画面黑**。

复现路径：`0 → 1 → 2 → 3 → 2 → 1 → 0`（3 player pool，offscreenPageLimit=1）。回到 pos 0：audio 正常，视频区黑矩形。

## ❌ 根因（三事实合体）

1. **`PlayerView.setPlayer(player)` 同实例直接 early return**（Media3 设计）：
   ```java
   public void setPlayer(@Nullable Player player) {
       if (this.player == player) return;   // ← 不重新走 setVideoSurfaceView
   }
   ```
2. **Pool 把同一 player 实例在多个 position 间复用**，player.videoSurface 跟着改写到不同 PlayerView
3. **RecyclerView 缓存让原 ViewHolder 持有旧 player 引用**，bind 不会再触发清理

→ 回到原位置时 `PV.setPlayer(samePlayer)` 静默 no-op，surface 留在另一 PV（屏幕外不可见）→ 黑屏。audio 正常因为 audio output 不依赖 surface。

## ✅ 正确

- Pool 把 player 放回 idle / 重新分配前必 `clearVideoSurface()`
- `attachPlayer` 同实例时显式 `set null` 再 `set player`（绕 early return）：
  ```kotlin
  fun attachPlayer(player: ExoPlayer?) {
      if (playerView.player === player && player != null) {
          playerView.player = null   // 逼 PV.this.player 改变
      }
      playerView.player = player
  }
  ```
- ViewHolder 用 `surface_type="texture_view"`（SurfaceView 生命周期更脆弱，ViewPager2 复用偶发黑）

### 复发加剧器 — STATE_READY 不等于 surface 在渲染

`Player.STATE_READY` 仅代表 codec 准备好，**不代表帧已上屏**。任何依赖"player ready 就隐藏占位/loading"的 UI logic ❌，必须用 `onRenderedFirstFrame()`：

```kotlin
// ❌ 错误（会黑屏）
override fun onPlaybackStateChanged(playbackState: Int) {
    if (playbackState == Player.STATE_READY) hideLoading()  // STATE_READY ≠ 帧上屏
}

// ✅ 正确
override fun onRenderedFirstFrame() { hideLoading() }
```

## 调用方加 guard 跳过 attachPlayer（变种）

现象：`if (!alreadyAttached) holder.attachPlayer(player)` — 引用相同时跳过 attach，意图防封面重复显示。

隐患：`alreadyAttached` 仅判断"引用相同"，**不代表 surface 已 bound + codec 未换**。池复用场景下引用相同但 `clearVideoSurface()` 已调或 codec 已换 → 跳过 attachPlayer = 跳过 setVideoTextureView 重跑 = 黑屏。

**职责分离铁律**：
- `attachPlayer` = surface bind 路径 → **必须无条件调用**，任何 guard 均违规
- `showLoading` / `hideLoading` = UI 状态切换 → 可受 `alreadyAttached` guard 防闪回

```kotlin
// ❌ 错误（调用方变种）
if (!alreadyAttached) {
    holder.attachPlayer(player)      // ← guard 导致池复用时漏 setVideoTextureView 重跑
    holder.showLoading(hasThumbnail)
}

// ✅ 正确（职责分离）
holder.attachPlayer(player)          // ← 无条件
if (!alreadyAttached) {
    holder.showLoading(hasThumbnail) // ← UI 状态，guard 只保护这行
}
```

根本解法：引入 `pendingRebind` marker（coordinator 层），区分"引用相同 + 无 rebind 需求"（可跳过 null/assign）vs "引用相同 + codec 换了"（必须强制重 bind）。

## iOS 镜像可能

iOS 当前用单 AVPlayer 不池化，未触发。若未来切到 AVQueuePlayer / 多实例池 + UICollectionView 复用，需先验证 `AVPlayerLayer.player = samePlayer` 是否同样 early return。

## lint 状态

- Android: ✅ grep `attachPlayer` 函数体必含 `playerView.player = null`；v2 追加调用方 guard 盲区扫描
- iOS: ❌ N/A（未池化）

## 关联

- 反模式 0023（Feature 不应自建 player 实例）— 本节是池化复用后的下一层陷阱
