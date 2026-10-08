---
doc_id: "ap-0101"
container: anti-patterns
platform: android
summary: "Android core-network factory 多实例化反模式"
---

# 0101 — Android core-network factory 多实例化反模式

- **平台**:Android(iOS `URLSession.shared` 系统级单例不犯此错,对照模式)
- **复发次数**:1

> 多个 Feature 业务 Api 都走同一 baseUrl,但 DI 内每个 `single<XxxApi>` 各自调 factory `OkHttpClient.Builder().build()` → N 个独立 OkHttpClient,各自的 `ConnectionPool` / DNS cache / TLS session **不共享** → cold start 首次建连多 300-500ms。

## ❌ 错误

跨多 Feature 都走同一 baseUrl,但 DI 内每个 `single<XxxApi>` 调用同一 factory `ApiClient.create(...)` 各自 `OkHttpClient.Builder().build()` → N 个独立 OkHttpClient,`ConnectionPool` / DNS / TLS session 不共享。

```kotlin
object ApiClient {
    fun create(baseUrl: String, ...): Retrofit {
        val client = OkHttpClient.Builder()    // ← 每次新建
            .addInterceptor(...)
            .build()
        return Retrofit.Builder().client(client).baseUrl(baseUrl).build()
    }
}
// DI 各 Api 走 factory:
single<XxxApi> { ApiClient.create("https://api.x.com/").create(XxxApi::class.java) }
single<YyyApi> { ApiClient.create("https://api.x.com/").create(YyyApi::class.java) }
// ↑ 同 baseUrl 不共享 OkHttpClient,各自的 ConnectionPool 互不复用
```

cold start 用户首次进某页触发该 Api → 该 client 的 ConnectionPool 空 → 全新 DNS 解析 + TLS 1.3 handshake + TCP/ALPN ≈ 300-500ms 额外建连开销。

**iOS 对照不犯**:`URLSession.shared` 系统级单例,整 App 多 Client 共享同一 session → 启动期已建好 h2 连接,后续任一 Api 自然复用。

## 为什么错

| 原因 | 说明 |
|---|---|
| 1. factory 方法无 client 缓存语义 | `fun create(...)` 每次调用新建 `OkHttpClient.Builder().build()`,无 instance 共享标识 |
| 2. DI 层未察觉 factory 副作用 | Koin `single<XxxApi> { ApiClient.create(...) }` 看似"single"了 Api,底下 OkHttpClient 仍每次新建 |
| 3. 注释误导 | 旧注释"共享同一个 OkHttp / token 配置" — 只共享配置参数,不共享 client 实例 |
| 4. iOS 对照模式难复制 | iOS `URLSession.shared` 是平台单例 + 系统级 ConnectionPool;Android OkHttp 无对应平台单例,需业务层显式 object 包装 |
| 5. cold start 边界条件少触发 | 用户启动后通常先走其他页,不显眼,直到 audit 实测才暴露 |

## ✅ 正确

```kotlin
object ApiClient {
    @Volatile private var sharedClient: OkHttpClient? = null
    @Volatile private var sharedRetrofit: Retrofit? = null

    fun install(cacheDir: File, baseUrl: String, ...) {
        sharedClient = OkHttpClient.Builder()
            .cache(Cache(File(cacheDir, "api_http_cache"), 64 * 1024 * 1024))
            .protocols(listOf(Protocol.HTTP_2, Protocol.HTTP_1_1))   // 防 ALPN 降级
            ...
            .build()
        sharedRetrofit = Retrofit.Builder().client(sharedClient!!).baseUrl(baseUrl).build()
    }

    inline fun <reified T> create(): T = sharedRetrofit!!.create(T::class.java)
}
// DI 各 Api:
single<XxxApi> { ApiClient.create<XxxApi>() }
single<YyyApi> { ApiClient.create<YyyApi>() }
// ↑ 全部 Api 共享同一 OkHttp + ConnectionPool + DNS cache + TLS session
```

配套:启动期 `install` + 后台静默 prefetch 让 ConnectionPool 暖 + DNS 已解;独立 baseUrl(如另一组 Agent Api)抽独立 client object,不混业务 ApiClient。

## lint 状态

```bash
# 检测:同一 baseUrl 下 OkHttpClient.Builder() 实例化 > 3 处
# 预期上限:1 业务 ApiClient + 1 独立 baseUrl client + 1 图片 loader
COUNT=$(grep -rE 'OkHttpClient\.Builder\(\)' core-network/src/main/ | grep -v 'Test' | wc -l | tr -d ' ')
if [ "$COUNT" -gt 3 ]; then
    echo "⚠️ §0101 触发:OkHttpClient.Builder() 实例化 $COUNT 处(预期 ≤3)"
    exit 1
fi
```

iOS 对照不需要:URLSession.shared 系统级单例,平台保证。

## 检测路径

写新 Api / 新 NetworkClient 前必跑:

```bash
grep -rnE 'object .*ApiClient|class .*ApiClient|fun create.*OkHttp' core-network/
# 若已有 ApiClient 单例 → 直接 ApiClient.create<NewApi>(),不新建
# 若新 baseUrl → 单独抽 NewClient object,不混业务 ApiClient
```

## 关联

- 关联反模式:协调端起草 task md 前先跑 baseline 实证(本案 audit + fix 一次性走 baseline 5 步)
