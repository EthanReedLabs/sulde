---
doc_id: "ap-0162"
container: anti-patterns
platform: cross
summary: "0162 MVI reducer 硬编码用户可见字符串导致 i18n 泄漏"
---

# 0162 MVI reducer 硬编码用户可见字符串导致 i18n 泄漏

- **平台**:跨端
- **复发次数**:0

## ❌ 错误

MVI reducer / Store 给错误提示或 Toast 直接传入硬编码英文字符串，或把服务端返回的英文 message 直接展示给用户。表现层又做本地化兜底时，还可能对同一错误重复提示，形成语言混杂。

## 为什么错

- reducer / Store 属于状态逻辑层，直接使用裸字符串会绕过资源系统。
- 服务端 message 的语言不可由客户端控制，不应直接作为用户可见文案。
- 常见本地化 lint 只扫描布局或资源文件，容易漏掉状态逻辑代码中的字符串字面量。

## ✅ 正确

- Android 状态层传递 `@StringRes Int`，由 Fragment / Activity 调用 `getString()` 后展示。
- 其他平台传递本地化 key 或类型安全的本地化标识，在表现层解析。
- 禁止将服务端 message 直接透传为用户提示；需要记录时仅用于日志或诊断。
- 同一错误只由一层负责提示，避免状态层和表现层重复弹出。

## lint 状态

- ✅ 可 lint：扫描 reducer / Store 中错误提示 API 的字符串字面量，并将状态逻辑代码纳入本地化硬编码检查。
- 人工 review：检查服务端 message 是否进入用户可见组件，以及错误提示是否存在双重消费。
- 关联：同属状态层与本地化资源边界问题。
