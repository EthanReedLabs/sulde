---
doc_id: "ap-0126"
container: anti-patterns
platform: cross
summary: "0126 异步渲染期必须有明确\"合成中\"态 + 不露占位 fallback"
---

# 0126 异步渲染期必须有明确"合成中"态 + 不露占位 fallback

- **平台**:协调端 / Android / iOS
- **复发次数**:0

## ❌ 错误

某成片需异步渲染(~1min),期间拿不到真成片 URL;旧实施在"上一步成功"时直接 fallback 播一个占位片段(~5s 静音子项 URL)当最终成片露出 + 装 player 可播:

```kotlin
// ❌ 上一步成功就装占位 fallback
private fun onStepSuccess(state: AgentState) {
    val fallbackUrl = state.items.values.firstOrNull()?.url
    binding.player.setMediaItem(MediaItem.fromUri(fallbackUrl))
    binding.player.play()
    // 渲染还没发起,装的是 5s 静音占位 — 用户误以为这就是成片
}
```

后果:用户看到"5s 已播完"以为完成;点重播又是 5s;时长标签(来自参数预估)与实际不符;播完停黑屏像播放器坏了。

## 为什么错

- 旧实施假设"上一步成功 = 成片就绪",但真链路是异步渲染,success ≠ 成片就绪。
- 没区分"成片就绪"vs"渲染中"两态,只一个 url 字段,fallback 串到占位看似合理实际误导。
- 播放结束后不回封面,默认停在末帧(黑屏)。

## ✅ 正确

ViewModel/Feature 必有显式"渲染中"flag + UI 三态切换,严禁 fallback 直装占位为最终成片:

```kotlin
data class UiState(
    val finalVideoUrl: String? = null,           // 只有渲染完成才填
    val isFinalMergeRendering: Boolean = false,  // 渲染期 true
    val playbackEnded: Boolean = false,
)

private fun renderState(state: UiState) = when {
    // 1. 渲染期:不露占位,显遮罩 + 清 player + 时长归零
    state.isFinalMergeRendering -> {
        binding.player.clearMediaItems(); binding.durationLabel.text = "0:00 / 0:00"
        binding.renderingMask.isVisible = true
    }
    // 2. 真成片到 + 未播完:装 player + 真时长
    state.finalVideoUrl != null && !state.playbackEnded -> {
        binding.player.setMediaItem(MediaItem.fromUri(state.finalVideoUrl))
        binding.renderingMask.isVisible = false
    }
    // 3. 播完:恢复封面,不黑屏
    state.playbackEnded -> { binding.coverImage.isVisible = true; binding.player.setVideoSurface(null) }
}

// 渲染期点播 → toast
private fun onPlayTapped() {
    if (vm.state.value.isFinalMergeRendering) { Toast.show("请稍候"); return }
    binding.player.play()
}
```

原则:
1. 必有 `isFinalMergeRendering` 显式 flag,不允许"由 url 是否 null 推断渲染态"(空可能是渲染中也可能是失败)。
2. UI 三态切换严禁 fallback 直装占位为最终成片;占位仅作渲染失败 / 超时兜底。
3. 渲染期点播必 toast,播放结束必恢复封面(Android STATE_ENDED / iOS AVPlayerItemDidPlayToEndTime)。
4. 协调端 task md 涉及最终成片 / 播放页必含 UI 三态契约段。

## lint 状态

⏳ pending — grep 成片页 player 装载(setMediaItem / replaceCurrentItem)是否 gate `isFinalMergeRendering` flag;未 gate → 软警告。

## 关联

- 后端错误话术 UI 抽象不匹配(同源:UI 体验 vs 后端数据契约不匹配)
- 后续播放期同源坑:自定义播放器漏 STATE_ENDED 处理
