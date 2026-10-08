---
doc_id: "ap-0176"
container: anti-patterns
platform: ios
summary: "0176 security-scoped URL 未在授权窗口内复制"
---

# 0176 security-scoped URL 未在授权窗口内复制

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

将文档选择器返回的外部 URL 直接跨越 action、队列或其他异步边界，等后续任务真正消费时才读取文件。

```swift
guard let selectedURL = urls.first else { return }
send(.fileSelected(selectedURL))
```

## 为什么错

外部 URL 指向其他容器，读取能力由 security scope 临时授予。后续任务开始读取时，授权窗口可能已经结束；模拟器或同步读取小文件可能掩盖真机失败。跨边界前应先把外部能力转换成本应用沙盒内可持续访问的资产。

## ✅ 正确

在授权窗口内调用 `startAccessingSecurityScopedResource()`，将文件复制到本地临时目录或持久目录，并用 `defer` 配对调用 `stopAccessingSecurityScopedResource()`：

```swift
let didAccess = selectedURL.startAccessingSecurityScopedResource()
defer {
    if didAccess { selectedURL.stopAccessingSecurityScopedResource() }
}
try FileManager.default.copyItem(at: selectedURL, to: localURL)
send(.fileSelected(localURL))
```

复制完成后只向异步链路传递本地 URL，并明确清理策略。

## lint 状态

- ⏳ 可软扫文档选择回调中外部 URL 是否未经复制就进入异步 action。
- CI：以真机文件导入测试覆盖授权窗口结束后的读取。
- 关联：security scope 与 Android URI grant 都属于跨容器能力边界。
