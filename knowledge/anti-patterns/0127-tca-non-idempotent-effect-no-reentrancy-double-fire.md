---
doc_id: "ap-0127"
container: anti-patterns
platform: cross
summary: "0127 TCA / MVI effect 发非幂等网络副作用无防重入 + 非 cancellable → 多触发源双发"
---

# 0127 TCA / MVI effect 发非幂等网络副作用无防重入 + 非 cancellable → 多触发源双发

- **平台**:iOS / Android
- **复发次数**:0

## ❌ 错误

登录验证码填满后,逐格 onChange 路径 + 系统短信自动填充 paste 路径在最后一位**同帧各触发一次** verifyCodeAuto;effect 既无防重入 guard 也非 cancellable:

```swift
// ❌ TCA
case .view(.verifyCodeAuto):
    guard state.code.count == 6 else { return .none }
    state.loginState = .loading      // 无 guard state.loginState != .loading
    return .run { send in
        let session = try await authClient.loginWithEmailCode(...)  // 非 cancellable
        await send(.loginSucceeded(session))
    }
```

真因链:同验证码双发 loginV2(间隔 2ms)→ 第一个成功客户端存 token → 后端单会话契约让先到 token 失效 → 客户端持失效 token → 401「另一设备登录」→ 登录弹窗反复弹。

## 为什么错

- **TCA / MVI 默认不防重入**:多次触发 effect 默认各自启动,对幂等读取无害,对非幂等副作用(login / submit / 创建 / 支付)致命。
- **多触发源易遗漏**:开发者只关注"填满即触发",忽略两路径同帧各触发一次。
- 后端单会话契约不明示 + 高阶"已登出"事件无条件重弹 = 放大效应。

## ✅ 正确

防重入 guard + cancellable 单飞兜底:

```swift
// ✅ TCA
case .view(.verifyCodeAuto):
    guard state.code.count == 6 else { return .none }
    guard state.loginState != .loading else { return .none }   // ⭐ 防重入
    state.loginState = .loading
    return .run { send in ... }
    .cancellable(id: CancelID.verify, cancelInFlight: true)    // ⭐ 单飞兜底
```

按架构选实施:

| 架构 | 主修 | 兜底 |
|---|---|---|
| TCA | `guard state.loadingFlag != .loading` | `.cancellable(id:, cancelInFlight:true)` |
| MVVM ViewModel + Job | `if (state.isLoading) return` | `loginJob?.cancel() + viewModelScope.launch { ... }` |
| MVI + Channel 串行 collect | reducer guard `if (state.isLoading) return` | handler 内 `verifyInFlight` 布尔 reject-duplicate |

**铁律**:涉及非幂等 effect 的 task md,Stage 2 模板写法前**必先 grep 实际架构**(ViewModel/Job vs UiBinder/Channel)。禁凭"通用范式"假设硬套 — 串行 collect 架构硬套 Job-cancel 会引入本不存在的并发。

同类风险清单:Submit 创建(双 submit 扣双费)/ 支付(双 commit)/ 上传下载(孤儿文件)/ 删除(双删 404)。协调端 task md 涉上述 + "自动触发 / 多 UI 触发源"必含 §防重入契约段(触发源清单 + 防重入策略 + 抓包 verify 只调 1 次)。

## lint 状态

❌ 无法可靠静态检查(需语义判断 effect 是否幂等 + 是否多触发源)→ 仅人工 review + /code-review checklist 加一条:"非幂等网络副作用 effect 是否有防重入 guard / cancellable?"

## 关联

- 自发修复路径(scope 扩散容忍判定)
- 高阶"已登出"等 effect 必区分"已有有效新 session 时的滞后事件" → 忽略,否则放大症状
