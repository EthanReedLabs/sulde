---
doc_id: "ap-0137"
container: anti-patterns
platform: cross
summary: "0137 Real adapter 委托 mock 导致数据源失真"
---

# 0137 Real adapter 委托 mock 导致数据源失真

- **平台**:iOS / Android(跨端架构对照)
- **复发次数**:0

## ❌ 错误

production adapter(`Real*Adapter`)实现某 method 时**委托给 mock adapter** 兜底(懒实施 / 未完成迁移 / 保留 mock 测试用)。production runtime 仍用 mock 数据,但代码看起来已实施:

```swift
class RealAuthAdapter: AuthClient {
    let mockFallback = MockAuthAdapter()
    var currentUser: AsyncStream<UserInfo?> {
        mockFallback.currentUser   // ⚠️ 委托给 mock,永真
    }
}
```

后果(所有 caller 凭 method 名假设"数据源正确",实际基于失真值):

| caller | 假设 | 真值 |
|---|---|---|
| 某 Feature | `isLoggedIn = currentUser != nil` | 永真 → 登录态失真 |
| submit 守卫 | `guard isLoggedIn else { ... }` | 永真 → **守卫永不触发**(未登录也能 submit)|
| stream 监听 | 监听 currentUser 变化 | 永真不变 → **stream 永不 emit** → 登录检测死 |

## 为什么错

`Real*Adapter` 类型存在 + DI 注入 + method 存在 → 表面像已实施;真值 method body 仅 `return mockFallback.xxx`(永真 / 硬编码)。grep method 名 ≠ runtime 真实施。

## ✅ 正确

数据源切到真 SSOT(登录态走 accessToken,非 user object):

```swift
// 绕开 mock 失真的 authClient.currentUser,直接订阅 SessionClient SSOT
@Dependency(\.session) var session
for await s in await session.sessionStream() {
    await send(.authStateChanged(isLoggedIn: s.isLoggedIn))
}
```

另一端架构领先样板(SSOT 接口):

```kotlin
interface SessionService {
    val isLoggedInFlow: Flow<Boolean>
    val isLoggedIn: Boolean get() = accessToken != null  // ✅ accessToken SSOT
}
```

铁律:
1. **production adapter 禁止委托 mock**:`Real*Adapter` 必须实施完整真实数据源,mock 仅 testing/dev DI。
2. **登录态 SSOT 必走 accessToken**(非 user object):SessionStore 可能保留内存 user 防闪烁 → `user != nil` 不可靠。
3. adapter method 必有 production 路径文档(注释明示"production 走 API/cache,mock 仅 testing")。
4. 发现一端架构滞后 → 全 consumer audit + 迁移。
5. 协调端 audit 前必先 Read method body verify "Real adapter 真实施 vs 委托 mock",不凭 method 存在 = 实施完整。

## lint 状态

❓ — grep `Real*Adapter` 内 `mockFallback.` / `return mock`;grep 登录态判 `currentUser != nil` / `user != nil`(应走 isLoggedIn / accessToken SSOT)→ 警告。

## 关联

- 协调端凭印象判"已实施"(反向 — 实际 Real adapter 委托 mock 失真)
- grep method 名 ≠ runtime 真实施
