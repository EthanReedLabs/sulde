---
doc_id: "tech-docs/案例研究/04-移动端缓存架构/缓存SWR陈旧重验策略"
container: case-studies
platform: none
summary: "**技术域**：移动端缓存架构 / iOS TCA / Android 状态管理 / UserDefaults / S…"
---

# 移动端用户资料缓存的 Stale-While-Revalidate 策略案例研究

> **技术域**：移动端缓存架构 / iOS TCA / Android 状态管理 / UserDefaults / SharedPreferences
> **难度**：⭐⭐⭐⭐
> **关键词**：stale-while-revalidate / 用户资料缓存 / 冷启动 / UserDefaults / SharedPreferences / Codable / JSON / TCA @Dependency / 骨架占位 / 静默刷新
> **可迁移场景**：用户资料页、会员状态、积分余额、钱包概览、权限状态、弱网首屏、杀进程重启后的本地数据恢复

---

## 场景与系统架构

某移动端应用的用户资料页需要展示头像、昵称、会员状态、积分等信息。旧链路在冷启动或杀进程重启后，进入资料页时先等待远端接口，期间用户看到全屏 loading 或默认占位，接口返回后才填充真实数据。网络稍慢时，用户会明显感到“进页面先转圈，数据慢”。

这类页面适合使用 **stale-while-revalidate（SWR，陈旧可用 + 后台重验）**：先展示本地旧值，让页面立即可用；同时后台请求远端最新值；远端成功后静默合并并更新本地缓存。

### 用户资料页三级数据来源

```
L1 本地持久化
├── iOS：UserDefaults + JSON / Codable
└── Android：SharedPreferences + JSON
        │
        ▼
L2 进程内状态
├── iOS：TCA State + @Dependency 注入的 cache client
└── Android：Store / ViewModel 状态
        │
        ▼
L3 远端接口
└── getProfile / mine / membership / credits 等用户资料接口
```

### SWR 三态链路

```
onAppear / onViewCreated
        │
        ├── 1. 读取 L1 cache
        │       ├── hit：立即 hydrate L2，页面秒显旧值
        │       └── miss：展示轻量骨架 / 默认占位，不全屏转圈
        │
        ├── 2. 后台 refresh L3
        │       └── 不阻塞首屏
        │
        └── 3. refresh 成功后 merge
                ├── 更新 L2 当前页面状态
                ├── save 到 L1
                └── 静默刷新 UI
```

这个设计的目标不是让旧值永远替代远端，而是把“可见首屏”和“数据重验”拆开：页面先可用，数据再变新。

---

## 问题现象

用户可见问题集中在冷启动和杀进程重启：

1. 已登录状态下进入资料页，先看到全屏 loading 或明显空态。
2. 杀进程后重启，再进入资料页，仍然等待接口返回才显示真实资料。
3. 网络较慢时，昵称、积分、会员状态等字段延迟填充。
4. 用户资料页和相关入口的体验不一致：有的地方已经有历史数据，有的地方仍按“未知”处理。

Android 侧实测体现了 SWR 的收益边界：

| 场景 | 改造前体验 | 改造后实测 |
|---|---|---|
| 已登录首次进资料页且无 cache | 转圈等待接口 | 不转圈，先显示骨架/占位，接口约 1101ms 后填充 |
| 杀进程重启后进资料页且有 cache | 等接口返回 | cache 命中后秒展示，再后台 refresh |

iOS 侧完成了启动期 wiring 和缓存链路验证，用户体验场景需要人工操作验证；代码链路具备 L1 读、远端刷新、成功写回、登出清理和用户作用域保护。

---

## 根因与设计

### 根因一：页面把“没有最新数据”等同于“不能展示”

资料页旧链路通常是：

```swift
case .view(.onAppear):
    state.isLoading = true
    return .run { send in
        let profile = try await api.getProfile()
        await send(.profileLoaded(profile))
    }
```

或 Android 等价流程：

```kotlin
override fun onViewCreated(...) {
    store.send(LoadProfile)  // UI 进入 loading，等待远端结果
}
```

这会把远端接口变成首屏展示的前置条件。只要接口慢，资料页就慢；杀进程后即使本地曾经有过资料，也无法先展示。

SWR 的判断不同：旧值虽然可能陈旧，但对用户资料页而言通常比全屏 loading 更有价值。只要缓存作用域安全，旧值可以先展示，再由后台刷新覆盖。

### 根因二：缓存必须有用户作用域，否则可能跨账号泄露

用户资料缓存不能只按固定 key 存一份数据，除非产品明确不支持未登出直接切账号，且登出一定清理。更通用的安全设计是给缓存加 `user_id` scope：

```
cache entry
├── userId
├── profile payload
└── cachedAt（可选）

load(currentUserId)
└── entry.userId == currentUserId ? entry.profile : nil
```

iOS 侧采用了 `user_id` scope：读取时校验当前用户 id，错配直接返回 nil，避免展示前一个账号的资料。Android 侧本次实测实现是 MVP 单槽缓存：登出和删除账号时主动清理，未覆盖“未登出直接切账号”的严格 user_id 校验场景；如果产品后续支持直接切账号，应先补齐用户 id 的持久化和按用户读取。

这一区分很重要：SWR 允许展示旧值，但只能展示“当前用户的旧值”。

### 根因三：logout 清缓存，401 静默失效不一定清缓存

缓存失效语义不能一刀切。两个场景应区分：

| 场景 | 用户语义 | 缓存处理 |
|---|---|---|
| 用户主动 logout / delete account | 用户明确退出当前身份 | 清理用户资料缓存，防止下次误显 |
| 服务端 401 / token 过期 / 被踢下线 | 会话失效，但用户可能重新登录同账号 | 可保留资料缓存，重登后用于秒显，再后台重验 |

iOS 侧设计中，主动登出会清 profile cache；401 静默链路不清该缓存，避免同账号重新登录后失去 SWR 秒显能力。Android 侧实测实现中，logout 和 delete account 会清理缓存。

这个设计的核心是：缓存清理应跟随用户语义，而不是跟随所有鉴权事件。否则一次短暂 token 失效就会让资料页退回全屏 loading。

### 根因四：持久化对象必须可序列化

资料缓存要落到 L1，就必须把 profile、会员状态、订阅状态等结构序列化。iOS 侧使用 `Codable` + `JSONEncoder` / `JSONDecoder` 写入 `UserDefaults`；Android 侧使用 `SharedPreferences` 存 JSON 字符串。

示意结构：

```swift
struct ProfileInfo: Codable, Equatable, Sendable {
    var user: User
    var credits: Int
    var subscription: SubscriptionState
}
```

如果某个嵌套字段不可序列化，L1 写入就会断裂；如果解码失败后没有兜底，冷启动读取也会失败。SWR 的缓存 client 必须把 load/save/clear 作为完整契约，而不是散落在页面里临时读写。

---

## 解决方案

### 方案一：抽象 Profile Cache Client

定义一个缓存 client，统一提供 `load`、`save`、`clear`：

```swift
struct ProfileCacheClient {
    var load: (_ currentUserId: String) -> ProfileInfo?
    var save: (_ profile: ProfileInfo, _ currentUserId: String) -> Void
    var clear: () -> Void
}
```

iOS 侧可通过 TCA `@Dependency` 注入：

```swift
@Dependency(\.profileCache) var profileCache
```

Android 侧可通过依赖注入或构造参数注入：

```kotlin
class ProfileCacheStorage(
    private val prefs: SharedPreferences
) {
    fun load(): UserProfile?
    fun save(profile: UserProfile)
    fun clear()
}
```

接口的重点不是具体命名，而是把缓存读写收敛到一个边界：页面只表达“hydrate / refresh / clear”，不直接拼持久化 key。

### 方案二：onAppear / onViewCreated 先 hydrate，再后台 refresh

iOS 侧状态流可写成：

```swift
case .view(.onAppear):
    return .merge(
        .send(.result(.profileCacheHydrated(profileCache.load(currentUserId)))),
        .run { send in
            let profile = try await api.getProfile()
            await send(.result(.profileLoaded(profile)))
        }
    )
```

缓存命中时立即填充页面状态：

```swift
case .result(.profileCacheHydrated(let cached)):
    guard let cached else { return .none }
    state.currentUser = cached.user
    state.credits = cached.credits
    state.subscription = cached.subscription
    state.isLoading = false
    return .none
```

远端成功后更新状态并写回缓存：

```swift
case .result(.profileLoaded(let profile)):
    state.currentUser = profile.user
    state.credits = profile.credits
    state.subscription = profile.subscription
    profileCache.save(profile, currentUserId)
    return .none
```

Android 侧等价链路是：

```kotlin
override fun onViewCreated(...) {
    val cached = profileCacheStore.load()
    if (cached != null) {
        store.send(HydrateFromCache(cached))
    } else {
        store.send(InitWithSkeleton)
    }

    store.send(LoadProfile) // silent refresh
}
```

远端成功后写 cache：

```kotlin
fun onProfileLoaded(profile: UserProfile) {
    profileCacheStore.save(profile)
    store.send(ProfileLoaded(profile))
}
```

### 方案三：不要在 onAppear 中无条件设置 `isLoading = true`

SWR 的体验关键是：cache hit 时不要把页面重新打回 loading。

错误模式：

```swift
case .view(.onAppear):
    state.isLoading = true       // cache 即使命中，也先闪 loading
    ...
```

修复后：

```swift
case .view(.onAppear):
    // 不无条件置 true
    // cache hit -> 立即展示旧值
    // cache miss -> 轻量骨架或默认占位
    // refresh 在后台进行
```

如果 cache miss，页面可以展示骨架或字段级默认占位；如果 cache hit，则直接展示旧资料。远端 refresh 不应阻塞首屏。

### 方案四：登出和删除账号清缓存

主动退出身份时清理缓存：

```swift
case .result(.logoutSucceeded):
    profileCache.clear()
    state.currentUser = nil
    state.credits = 0
    state.subscription = nil
    return .none
```

Android 等价：

```kotlin
fun performLogout() {
    profileCacheStore.clear()
    sessionStore.clear()
}
```

如果是 401 静默失效，是否清 cache 取决于产品语义。若用户可能同账号重登，保留缓存可以继续支持秒显；若存在高安全要求，也可以选择清理，但必须明确代价。

### 为什么这样修，而不是其他方式

**不继续全屏转圈**：全屏 loading 把远端接口放在首屏前置路径上，弱网和冷启动体验都会差。SWR 能在安全作用域内先给旧值，避免闪烁。

**不每次都只打接口**：资料页数据通常可以接受短时间陈旧，且远端刷新仍会后台执行。每次都等待接口只会浪费已有本地数据。

**不把 cache 写在 View 层**：View 层读写持久化 key 会让缓存散落，难以处理 user scope、logout clear、序列化失败和测试。缓存应收敛在 client/store 边界。

**不把 Android 写成强 user_id scope**：本次 Android 实测实现是单槽缓存 + logout/delete 清理，能覆盖 MVP 冷启动秒显；严格跨账号隔离需要先补齐持久化用户 id，再升级为按 user_id load。

---

## 可迁移原则

### 1. SWR 适合“旧值比空白更好”的用户数据

用户资料、积分、会员状态、钱包概览、权限状态都适合先展示上次已知值，再后台重验。前提是旧值不会造成安全或交易语义错误。

### 2. 缓存必须有作用域

用户数据缓存默认应按 `user_id`、tenant、环境或账号维度隔离。没有作用域的单槽缓存只能用于明确不支持直接切账号、且登出必清的 MVP 场景。

### 3. logout 与 401 的失效语义不同

logout 是用户主动退出，应清缓存；401 可能只是 token 失效，未必代表用户资料不可再用。是否清缓存要按产品语义决定，而不是看到鉴权失败就全部删除。

### 4. 默认值和未知值要分开

`0 credits`、`free plan`、`User` 可能是真值，也可能是缓存 miss 的占位。状态层应区分 unknown、cached、fresh，UI 再决定如何展示。

### 5. 持久化要设计完整生命周期

缓存不是只有 `save`。必须同时设计 `load`、`save`、`clear`、序列化失败兜底、版本兼容和用户作用域校验。缺一项都会让 SWR 变成不可靠的“偶尔秒显”。

### 6. 双端对称不等于实现完全相同

iOS 可以用 `Codable` + `UserDefaults` + TCA `@Dependency`，Android 可以用 `SharedPreferences` + JSON + Store intent。关键是行为契约一致：先 hydrate，后台 refresh，成功 save，主动退出 clear。

---

## 技术深问 Q&A

### Q1：SWR 会不会让用户看到旧数据？

会，但这是有意设计。SWR 展示的是上次已知值，同时后台立即重验。对于资料页这类非交易数据，旧值通常比空白或转圈更好。关键是刷新成功后要静默更新。

### Q2：为什么 cache hit 时不能再设 `isLoading = true`？

因为这会让旧值先被 loading 覆盖，造成闪烁。SWR 的核心是 cache hit 直接展示，refresh 在后台进行。loading 只适合 cache miss 或必须阻塞的操作。

### Q3：为什么需要 user_id scope？

用户资料属于账号数据。如果不校验 user_id，A 用户缓存可能在 B 用户登录后被展示。即使只出现一瞬间，也是数据泄露。单槽缓存必须以“无法直接切账号 + 登出必清”为前提。

### Q4：为什么 401 不一定清缓存？

401 表示当前 token 不可用，不一定表示用户资料不应继续作为本地旧值展示。若用户重新登录同账号，保留缓存能继续秒显。是否清理要看安全要求和产品语义。

### Q5：JSON 序列化失败怎么办？

`load` 失败应返回 nil，让页面走 skeleton + refresh；`save` 失败应记录但不阻断页面状态更新。不要因为缓存失败影响远端数据展示，但要保证失败可观测。

### Q6：如何验证 SWR 真正生效？

至少覆盖四类场景：无缓存首次进入不全屏转圈；有缓存杀进程重启秒展示；远端成功后缓存被覆盖；登出或删除账号后缓存被清理。若支持切账号，还要验证 user_id 不匹配时不展示旧缓存。
