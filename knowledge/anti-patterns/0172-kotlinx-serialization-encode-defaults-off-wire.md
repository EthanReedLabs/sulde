---
doc_id: "ap-0172"
container: anti-patterns
platform: android
summary: "0172 kotlinx.serialization 默认值未编码导致协议必填字段缺失"
---

# 0172 kotlinx.serialization 默认值未编码导致协议必填字段缺失

- **平台**:Android
- **复发次数**:1

## ❌ 错误

请求模型为协议必填字段声明默认值，却使用未显式开启默认值编码的 `Json` 配置：

```kotlin
private val json = Json {
    ignoreUnknownKeys = true
}
```

当字段值等于声明的默认值时，`kotlinx.serialization` 默认可能不把它写入请求 JSON。

## 为什么错

Kotlin 构造参数的默认值是内存语义，不是 wire 契约。编码器为缩小 payload 省略默认值属性时，请求仍能编译并发出，但协议必填字段已经缺失。多个 `Json` 或 converter 实例配置不一致，还会让不同链路产生难以察觉的编码漂移。

## ✅ 正确

协议要求默认值也必须出现时，在所有负责该协议的序列化实例中显式开启：

```kotlin
private val json = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
}
```

同时用请求契约测试断言必填字段实际出现在编码结果中；不能只检查对象构造后的内存值。

## lint 状态

- ⏳ 可 lint：扫描 `Json {}` 与 converter 配置是否显式声明 `encodeDefaults`。
- 人工 review：确认默认值字段是否属于协议必填项，并检查所有序列化入口配置一致。
- 关联：响应解码类型需以真实契约为准；请求编码也需验证最终 wire 形态。
