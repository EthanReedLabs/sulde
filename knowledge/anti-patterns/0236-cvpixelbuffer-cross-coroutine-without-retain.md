---
doc_id: "ap-0236"
container: anti-patterns
platform: ios
summary: "Kotlin/Native 在 AVFoundation 回调里取得 CVPixelBuffer 后直接送入协程或 channel，离开同步回调才尝试 lock/retain；底层帧已被回收或复用，消费侧会卡死、读坏数据或崩溃。"
related: [ap-0160, ap-0161]
sedimented_by: auto
---

# 0236 — AVFoundation 帧跨协程前未在回调窗口 retain

- **平台**：iOS / Kotlin Multiplatform / Kotlin/Native
- **复发次数**：1

## ❌ 错误

在 capture callback 中取得 `CVPixelBuffer`，把裸引用发送到异步 channel，回调返回后才在
协程中 `CVPixelBufferLockBaseAddress` 或 retain。AVFoundation/sample buffer 对帧的所有权
只覆盖同步回调窗口；返回后缓冲可能被池复用或释放，裸指针仍非空却已不再属于该帧。

## 为什么

- Kotlin 引用存活不等于 Core Foundation 对象所有权已增加；Native interop 不会替调用方
  自动延长借用缓冲的生命周期。
- 相机帧通常来自小型复用池，异步消费者稍慢就会读到下一帧内容，或在 lock/retain 时
  等待已进入异常状态的缓冲。
- 无界 channel 即使每帧都 retain，也会积压大量原生内存并阻塞采集链。

## ✅ 正确

1. 在 AVFoundation 回调尚未返回时立即 retain 像素缓冲，再把“已拥有”的引用入队。
2. 消费侧在 `finally` 中对每次 retain 做一次 release；解析、取消、异常和丢帧路径都必须
   平衡。入队失败或有界队列淘汰旧帧时，当场 release 被丢弃的引用。
3. 使用容量 1 或很小的有界 channel，并按业务选择 drop-oldest/drop-latest；实时分析通常
   宁可丢帧，不让旧帧积压。
4. `lockBaseAddress`/读取/`unlockBaseAddress` 只发生在已 retain 的生命周期内，不把 base
   address 指针继续传到更晚的异步任务。
5. 压测慢消费者、取消和高帧率，断言 retain/release 计数归零且没有池耗尽、卡死或帧串台。

## lint 状态

- ⚠️ 可检：capture callback 内把 `CVPixelBuffer` 直接发送到 coroutine/channel，却没有在
  send 前出现 retain；检查只是候选，仍需确认封装层是否已拥有引用。
- ✅ 测试门禁：所有成功 retain 必有取消安全的 release，队列淘汰分支也计入。
- ❌ 仅靠 Kotlin GC/ARC 状态不能证明 Core Foundation 生命周期正确。
