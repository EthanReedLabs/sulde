---
doc_id: "ap-0171"
container: anti-patterns
platform: ios
summary: "0171 actor 可重入导致同 key 请求未单飞"
---

# 0171 actor 可重入导致同 key 请求未单飞

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

文件缓存器先检查目标文件是否存在，随后直接跨过 `await` 发起下载；恢复执行后再写入同一目标路径，却没有记录按资源 key 区分的在途任务。

```swift
if fileExists(for: key) { return cachedURL(for: key) }
let temporaryURL = try await download(resourceURL)
try replaceCachedFile(for: key, with: temporaryURL)
```

## 为什么错

actor 只保证同步隔离片段互斥。执行到 `await` 时会让出 executor，另一个调用可进入 actor，并对同一 key 再次观察到缓存未命中。两个调用恢复后可能重复下载、互删临时文件或争抢同一目标路径。actor 隔离不等于“同 key 只有一个在途任务”。

## ✅ 正确

在资源缓存器内部维护按 key 索引的在途任务或订阅者集合。命中在途任务时复用结果；仅第一个调用创建任务，并在完成或失败后清理。

```swift
if let task = inFlight[key] {
    return try await task.value
}
let task = Task { try await downloadAndCache(key) }
inFlight[key] = task
defer { inFlight[key] = nil }
return try await task.value
```

若需要用 `AsyncStream` 广播进度，也应让同一 key 的订阅者共享一个生产任务，并明确处理取消、终止和最后事件重放。

## lint 状态

- ❌ 静态 grep 难以判断 `await` 两侧共享资源与 key 语义。
- CI：增加并发请求同一 key 时只触发一次底层下载、所有调用获得一致结果的测试。
- 关联：非幂等异步入口的防重入与按 key 单飞属于互补防线。
