---
doc_id: "ap-0169"
container: anti-patterns
platform: android
summary: "0169 长后台恢复只开启播放而不重建 surface 导致画面冻结"
---

# 0169 长后台恢复只开启播放而不重建 surface 导致画面冻结

- **平台**:Android
- **复发次数**:1

## ❌ 错误

持有长生命周期播放器和 `TextureView` 的视频列表从长时间后台恢复时，仅设置 `playWhenReady=true`，没有重建视频 surface。结果可能是声音和解码继续工作，但所有画面冻结，切换列表项也无法恢复。

## 为什么错

1. 页面隐藏后，`TextureView` 不参与绘制，但旧 `SurfaceTexture` 可能仍被保留。
2. 长后台期间，系统可能销毁并重建宿主 window surface 与 EGL 上下文。
3. 回前台时复用旧 `SurfaceTexture`，不会触发新的 `onSurfaceTextureAvailable`，播放器无法自动完成有效重挂。
4. 旧消费端仍关联已失效的 EGL 上下文，`updateTexImage` 不再消费帧，最终造成 BufferQueue 堵塞和画面冻结。

仅将播放器重新绑定到同一个旧 surface，或简单执行 `GONE → VISIBLE`，都没有修复陈旧的消费端 GL 关联。

## ✅ 正确

- 在真实后台进入与恢复路径中记录停止状态和持续时间。
- 超过合理阈值后，脱挂列表适配层、清理回收池并重新挂载，确保创建新的 `TextureView/SurfaceTexture`。
- 等待 `onSurfaceTextureAvailable` 后重挂播放器，再恢复当前位置与播放状态。
- 使用首帧缓存或占位图遮挡重建窗口；普通站内跳转应通过时间阈值或 `onStop` 门控排除，避免无谓闪烁。
- 对厂商后台限制与 MARs 等省电机制进行真机验证，但不要把进程限制误当成 surface 生命周期修复。

## lint 状态

- ❌ 难以静态检查：问题依赖生命周期、后台时长与图形上下文状态。
- 人工 review：持长生命周期播放器与 `TextureView` 的页面，恢复路径必须存在受门控的 surface 重建分支，而非只翻播放开关。
- 关联：播放器生产端重绑定与 `SurfaceTexture` 消费端重建是两条互补防线。

## 关联

- [`0026`](./0026-exoplayer-recyclerview-viewpager2-setplayer-early-return.md) — producer 端 surface 绑定复用陷阱;本条是 consumer 端 SurfaceTexture 重建,两者互补构成 surface 生命周期完整防线
