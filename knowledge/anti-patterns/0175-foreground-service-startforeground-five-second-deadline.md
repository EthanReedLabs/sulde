---
doc_id: "ap-0175"
container: anti-patterns
platform: android
summary: "0175 前台服务未在五秒时限内调用 startForeground"
---

# 0175 前台服务未在五秒时限内调用 startForeground

- **平台**:Android
- **复发次数**:0

## ❌ 错误

通过 `startForegroundService()` 启动服务后，先执行网络、文件、数据库或复杂校验，再调用 `startForeground()`：

```kotlin
performExpensivePreparation()
startForeground(notificationId, notification)
```

## 为什么错

系统要求前台服务在启动后约五秒内调用 `startForeground()`。任何耗时准备都可能越过硬时限并触发 `ForegroundServiceDidNotStartInTimeException`；把准备工作放进协程也不能代替及时完成前台化。

## ✅ 正确

完成必要的轻量同步参数校验后，立即创建通知并调用 `startForeground()`，再开始耗时工作：

```kotlin
validateRequiredArguments()
startForeground(notificationId, buildPlaceholderNotification())
launchExpensiveWork()
```

后续通过通知更新 API 刷新进度。还应在目标 Android 版本上验证通知权限、前台服务类型和启动限制。

## lint 状态

- ⏳ 可启发式扫描 `Service.onStartCommand()` 中 `startForeground()` 之前的潜在耗时调用。
- 人工 review：确认前台化之前仅保留不可省略的同步校验。
- 关联：前台服务启动时限属于 Android 生命周期硬约束。
