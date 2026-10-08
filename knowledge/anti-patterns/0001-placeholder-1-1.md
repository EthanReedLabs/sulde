---
doc_id: "ap-0001"
container: anti-patterns
platform: android
summary: "在每个页面单独修系统级问题"
---

# 0001 — 在每个页面单独修系统级问题

- **平台**:Android(同类原则适用 iOS)
- **复发次数**:多次

## ❌ 错误

```kotlin
// 在某 Fragment 中加硬编码避让状态栏
binding.title.setPadding(0, 24.dp, 0, 0)  // 硬编码状态栏高度
```

## 为什么错

- 状态栏高度因设备不同(24dp~48dp)
- 每个页面都要重复修
- 新页面又会忘加,再次出现 bug

## ✅ 正确

```kotlin
// 1. Activity 继承统一的自适应基类(AdaptiveBaseActivity)
class MainActivity : AdaptiveBaseActivity() {
    override fun fitConfig() = FitConfig(statusBar = true)
}
// 2. 所有页面自动避开状态栏,零业务代码
```

**原则**:系统级避让(状态栏 / 导航栏 / 键盘 / 安全区)属基类一次性职责,不在每个页面单独打补丁。

## lint 状态

- ❌ 静态可检:Activity 必须继承统一自适应基类(allowlist 例外页除外)→ 本地 lint 脚本可扫
