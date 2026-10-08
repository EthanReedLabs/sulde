---
doc_id: "ap-0123"
container: anti-patterns
platform: cross
summary: "0123 后端业务错误全 HTTP 200 + code≠0,客户端 HTTP 401/403 拦截器是死代码"
---

# 0123 后端业务错误全 HTTP 200 + code≠0,客户端 HTTP 401/403 拦截器是死代码

- **平台**:Android / iOS / 后端契约
- **复发次数**:1

## ❌ 错误

协调端凭行业惯例假设"后端用 HTTP 401/403 标识 token 失效 / 无权限",让 Dev wire `ForbiddenInterceptor` 处理:

```kotlin
class ForbiddenInterceptor : Interceptor {
    override fun intercept(chain: Chain): Response {
        val response = chain.proceed(chain.request())
        if (response.code == 403) {
            refreshCredits()   // 永远到不了这
        }
        return response
    }
}
```

强制坏 token 实证:**后端对无效 token 也返 HTTP 200**(当游客处理,余额置 0),**从不发 HTTP 401/403**。其他业务错误(not found / invalid / 额度不足)也全是 `HTTP 200 + {"code":-1,"msg":"..."}`。拦截器永不 fire = 死代码。

## 为什么错

- 协调端凭印象假设"后端用标准 4xx/5xx",没要求 Dev 先 force-test 真包 verify HTTP 状态码就写 task md。
- 该后端的所有"被拒"信号通道 = HTTP 200 + `code != 0` + `msg`(或余额降级置 0),不在 HTTP 状态码。

## ✅ 正确

在 ApiResponse 解析层统一处理 `code != 0`:

```kotlin
inline suspend fun <T> safeApi(block: suspend () -> ApiResponse<T>): Result<T> {
    val resp = block()
    if (resp.code != 0) {
        when (resp.msg) {
            "Insufficient credits" -> refreshCredits()
            "Invalid token", "Token expired", "Unauthorized" -> clearSession()
        }
        return Result.failure(BizException(resp.code, resp.msg))
    }
    return Result.success(resp.data)
}
```

协调端 task md 涉及"被拒 / 失效 / 无权限"信号处理时:**必先让 Dev force-test 实证 HTTP 状态码真值**(强制坏 token / 失效操作),不假设"后端用 HTTP 标准状态码";真值实证后再设计拦截层(HTTP 层 vs 业务层 vs ApiResponse 层)。

## lint 状态

⏳ pending — grep `ForbiddenInterceptor` / `if (status == 403)` 双端,实证为永不触发的死代码后软警告。

## 边缘风险

- token 降级时后端返余额 0 + HTTP 200:客户端会把余额刷成 0,401/403 拦截器都抓不到(它是 200)。无完美解,只能监控异常变化(余额突降 0 + 有充值历史 → 触发 re-login)。
- 若后端将来某 endpoint 改用 HTTP 401/403 → 现有死代码拦截器自动 fire,无副作用,保留无妨。

## 关联

- 凭印象不查实证(同源)
- 长期契约:业务"被拒"信号 = ApiResponse `code != 0` + `msg`,写入团队 onboarding 文档
