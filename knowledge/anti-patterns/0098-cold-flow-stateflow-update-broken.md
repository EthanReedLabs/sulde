---
doc_id: "ap-0098"
container: anti-patterns
platform: android
summary: "Cold flow 暴露 StateFlow 但更新链断 — 不订阅 events 的消费者读到永恒初始快照"
related: [ap-0209]
---

# 0098 — Cold flow 暴露 StateFlow 但更新链断 — 不订阅 events 的消费者读到永恒初始快照

- **平台**:Android（Kotlin Flow / StateFlow 模式;iOS 用永久 monitor 不踩此坑）
- **复发次数**:1
- **lint 状态**:⏳ pending（grep 规则草稿见末尾）

## 现象

某共享单例（如网络监听器）在 DI 层 `single { NetworkMonitor(androidContext()) }` 注入，对外暴露 3 类接口:

```kotlin
val isConnected: StateFlow<Boolean>          // hot，_isConnected.value 当前值
val networkQuality: StateFlow<NetworkQuality> // hot，同上
val events: Flow<NetworkEvent>                // 看似 hot，实为 cold callbackFlow
```

其中 `events` 实现是:

```kotlin
val events: Flow<NetworkEvent> = callbackFlow {
    val callback = object : NetworkCallback() {
        override fun onAvailable(network: Network) {
            _isConnected.value = true
            trySend(NetworkEvent.CONNECTED)
        }
        override fun onLost(network: Network) {
            _isConnected.value = false
            trySend(NetworkEvent.DISCONNECTED)
        }
    }
    cm.registerNetworkCallback(NetworkRequest.Builder().build(), callback)
    awaitClose { cm.unregisterNetworkCallback(callback) }
}.distinctUntilChanged()
```

**陷阱**:`callbackFlow` 是 **cold flow** — `registerNetworkCallback` 只在有 collector 订阅 `events` 时才执行。所以 `_isConnected.value` 的更新链**完全依赖至少一个消费者持续 collect events**。

**爆发场景**:
- 消费者 A 只读 `inject<NetworkMonitor>().isConnected.value` 不 collect events → callback 从未注册 → `_isConnected` 永远停在初始 false
- 消费者 B 用 `collect {}` → StateFlow 本身在更新，但 callback 未注册时 StateFlow 也永远不更新 → collect 卡在初始 false 永不触发
- 消费者 C 进入页面前未 init 消费者 → 第一次 collect events 时 callback 才注册，**进入前的状态切换全部丢失**

## 根因

| 原因 | 说明 |
|---|---|
| 1. callbackFlow 语义认知错位 | Dev 误以为"DI 单例 = hot"（因为 object 只创建一次），但 callbackFlow lambda 内的 `register` 是 collect-on-demand，不是 init-on-creation |
| 2. StateFlow 接口暴露误导 | `isConnected: StateFlow<Boolean>` 接口让消费者认为"读 .value 永远是最新真值"，实际更新链断在 callback 未注册 |
| 3. 跨端设计有指导但未对齐 | iOS 用永久 `NWPathMonitor` + 多订阅广播模式（init 时 start，不依赖 collector），Android 改造前未参考 |
| 4. 单测无法覆盖 | unit test 通常显式 `monitor.events.collect {}` 触发 callback，无法暴露"只读 isConnected 不 collect events" 的真实使用模式 |

## 修法

**核心**:cold callbackFlow → hot SharedFlow + 永久 register

```kotlin
class NetworkMonitor(context: Context) {
    private val cm = context.getSystemService(ConnectivityManager::class.java)
    private val _isConnected = MutableStateFlow(false)
    val isConnected: StateFlow<Boolean> = _isConnected.asStateFlow()

    private val _events = MutableSharedFlow<NetworkEvent>(
        replay = 0, extraBufferCapacity = 8, onBufferOverflow = BufferOverflow.DROP_OLDEST
    )
    val events: Flow<NetworkEvent> = _events.asSharedFlow().distinctUntilChanged()

    private val callback = object : NetworkCallback() {
        override fun onAvailable(network: Network) { _isConnected.value = true; _events.tryEmit(NetworkEvent.CONNECTED) }
        override fun onLost(network: Network) { _isConnected.value = false; _events.tryEmit(NetworkEvent.DISCONNECTED) }
    }

    init {
        cm.registerNetworkCallback(
            NetworkRequest.Builder().addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build(),
            callback
        )
    }

    fun cleanup() { runCatching { cm.unregisterNetworkCallback(callback) } }
}
```

**设计选择**:
- `replay = 0` — 新订阅者不收历史 event（避免重复触发已处理过的状态）
- `extraBufferCapacity = 8` — 防快速抖动（飞行模式快开关）期间丢失
- `DROP_OLDEST` — 保证 `tryEmit` 不阻塞 callback 线程（callback 在系统线程不可阻塞）
- `init` 块 register + DI 单例 — Application Context 全局唯一 register，无 leak 风险

## 反例 vs 正例

❌ 错误（单例对外暴露的 events 是 cold flow）:
```kotlin
val events: Flow<NetworkEvent> = callbackFlow { register(); awaitClose { unregister() } }
class LoginRetryViewModel(private val monitor: NetworkMonitor) : ViewModel() {
    fun retry() {
        if (monitor.isConnected.value) { // ❌ 永远 false，从未 register
            doLogin()
        }
    }
}
```

✅ 正确（events 是 hot SharedFlow，register 在 init 块）:
```kotlin
init { cm.registerNetworkCallback(request, callback) }
val events: Flow<NetworkEvent> = _events.asSharedFlow().distinctUntilChanged()
// 消费者:可直接 monitor.isConnected.value 读真值，无需 collect events
```

## Lint 规则草稿

```bash
# rules/009-cold-flow-stateflow-bypass.sh
# 规则:同一文件内同时含 callbackFlow + MutableStateFlow + asStateFlow → 软警告
# 例外:文件含 "init { register" 关键字（已永久 register 不踩此坑）

violations=$(grep -lE "callbackFlow" <util 源码目录>/ \
    | xargs grep -lE "MutableStateFlow" \
    | xargs grep -lE "asStateFlow" \
    | xargs grep -LE "init \{[^}]*register" 2>/dev/null)

if [ -n "$violations" ]; then
    echo "⚠️ cold callbackFlow 暴露 StateFlow 但 init 未永久 register"
    echo "$violations"
    exit 1
fi
```

## 检测路径（review 时 Dev 自审）

写"网络监听 / 后台监听 / 系统回调"类 task md 前:

1. 单例对外暴露的 Flow / StateFlow，更新源在哪个 lambda?
2. 若更新源在 callbackFlow / channelFlow lambda 内 → 任一消费者不 collect 此 Flow 就更新链断 → 必改 hot SharedFlow + init register
3. iOS / Android 同款单例必参考已有端（如 Android 参考 iOS 永久 NWPathMonitor 模式）

## 关联

- 协调端 audit 未走 git log verify 的复发模式（本反模式由 Dev 在 handoff 中主动登记建议）
- 自发修复边界
