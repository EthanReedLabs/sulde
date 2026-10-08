---
doc_id: "ap-0108"
container: anti-patterns
platform: cross
summary: "DI 单例 + 运行时配置 = stale state"
---

# 0108 — DI 单例 + 运行时配置 = stale state

- **平台**:Android(主)/ iOS(对照,设计折衷接受重启切换)
- **复发次数**:1

## ❌ 错误

DI 容器单例 + 运行时配置(prefs / UserDefaults / Feature Flag)— 单例创建时 `if(enabled)` 一锤定音被缓存,运行时 prefs 变化不会重新解析单例 → 进程不杀,旧实例继续 emit。

```kotlin
val debugTestModule = module {
    single<ChatStreamService> {
        val enabled = SettingsStore(get()).read().enabled  // ← 一锤定音
        if (enabled) {
            MockChatStreamAdapter(get(), get())  // ← Koin 缓存此实例
        } else {
            get<RealChatStreamAdapter>()
        }
    }
}
```

→ Koin `single<>` 创建时调一次 lambda,boolean 锁进单例;关 toggle 只改 prefs,**单例不重解析** → 进程不杀就 stale。

**实证**:prefs 已存 `false`,Mock 却仍在回放(pid 存活)。用户关 toggle、从最近任务划掉(进程未真杀),仍在测试态。

## 为什么错

| 原因 | 说明 |
|---|---|
| 1. DI 容器单例语义 | Koin `single<>` / TCA `static var liveValue` / `@Injected` 单例都是创建时锁定,第一次解析后缓存 |
| 2. prefs 变化不通知 DI | SharedPreferences / UserDefaults 改值后 DI 无 invalidation 机制,单例继续指向旧实例 |
| 3. 进程生命周期错觉 | 用户认为"重启 app"= "kill process" — 实际从最近任务划掉常不立即杀进程(后台保活 / suspend)→ 单例存活继续 emit |
| 4. boolean 锁进单例是甜区 | `if (prefs) A else B` 在 DI 注册处看起来语义清晰,但失去运行时可切换性 — 隐性技术债 |

## ✅ 正确(wrapper 现读)

```kotlin
single<ChatStreamService> {
    // single 固定 wrapper,内部每次现读 prefs
    MockChatStreamAdapter(
        fixtureLoader = FixtureLoader(get()),
        realFallback = get<RealChatStreamAdapter>(),
        settingsStore = SettingsStore(get())
    )
}

class MockChatStreamAdapter(
    private val fixtureLoader: FixtureLoader,
    private val realFallback: ChatStreamService,
    private val settingsStore: SettingsStore,
) : ChatStreamService {
    override fun streamSession(...): Flow<ChatStreamEvent> {
        val current = settingsStore.read()  // ← 每次调用现读
        return if (current.enabled) fixtureLoader.loadFixture(...).playback(speed = current.speed)
               else realFallback.streamSession(...)
    }
}
```

→ single 固定 wrapper(实例不变),开关判断移到每次方法调用时现读 prefs;切换下次生成即生效,**无需 kill 进程**。

```swift
// TCA — wrapper closure 每次 invoke 现读
extension Service: DependencyKey {
    static var liveValue: Service {
        Service(method: {
            if UserDefaults.standard.bool(forKey: "enabled") {
                return await MockService().method()
            } else {
                return await LiveService().method()
            }
        })
    }
}
```

## 检测路径(写新 DI 注册 / 新 Feature Flag 前必问 3 问)

1. **该单例的行为是否依赖运行时配置?**(prefs / UserDefaults / Feature Flag)— 是 → 走 wrapper 现读模式。
2. **是否能接受"重启进程才生效"语义?**(Debug 类工具可接受)— 否 → 必 wrapper。
3. **user 多久要切一次?** — 高频切换 → 必 wrapper。

## lint 状态

```bash
# 检测 DI 注册点 if/else + prefs 读取模式 — 高风险 stale state
KOIN_BAD=$(grep -rnE 'single<[^>]+>\s*\{' --include="*.kt" . \
    | grep -A 8 'single<' | grep -E 'if \(.*[Pp]refs|if \(.*[Ee]nabled|if \(.*[Ss]ettings' | wc -l | tr -d ' ')
[ "$KOIN_BAD" -gt 0 ] && echo "⚠️ §0108:single<> 注册块内 $KOIN_BAD 处含 if (prefs/enabled/settings) → 应改 wrapper 现读"
```

iOS 折衷:启动时读 UserDefaults(`prepareDependencies`),接受重启切换 — 不同设计折衷,user 若希望切换无需重启同样需 wrapper 改造。

## 关联

- §0107(fixture 必须镜像 wire — 同源 mock 沉淀)。
- "看似订阅实际 stale"类反模式(Cold flow 更新链断同源)。
