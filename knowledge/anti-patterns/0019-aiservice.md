---
doc_id: "ap-0019"
container: anti-patterns
platform: cross
summary: "Service 为每种类型写单独的方法"
---

# 0019 — Service 为每种类型写单独的方法

- **平台**:Android / iOS(接口设计同类)

## ❌ 错误

```kotlin
interface CreateService {
    suspend fun submitTypeA(req: TypeARequest): Result<...>
    suspend fun submitTypeB(req: TypeBRequest): Result<...>
    suspend fun submitTypeC(req: TypeCRequest): Result<...>
    // 新增类型要改接口 → 影响所有实现
}
```

## 为什么错

每加一种创作类型就要改接口签名,所有实现 / mock / 测试连带改;接口随业务无限膨胀。

## ✅ 正确

```kotlin
interface CreateService {
    suspend fun <T : CreateRequest> submit(req: T): Result<SubmitResult>
}
sealed class CreateRequest {
    data class TypeA(...) : CreateRequest()
    data class TypeB(...) : CreateRequest()
    // 新增类型只加子类,接口不变
}
```

**原则**:同形态的多类型操作,用 sealed/泛型收敛成单方法,把"类型差异"下沉到数据(sealed 子类),不上浮到接口签名。

## lint 状态

- ❌ 难静态检查 → 人工 review / 架构评审。
