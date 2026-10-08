---
doc_id: "ap-0018"
container: anti-patterns
platform: cross
summary: "Feature 直接依赖另一个 Feature"
---

# 0018 — Feature 直接依赖另一个 Feature

- **平台**:Android / iOS(模块化架构同类)

## ❌ 错误

```kotlin
// feature-A 模块的 build.gradle.kts
dependencies {
    implementation(project(":feature-B"))  // ❌ Feature 间禁止直接依赖
}
```

## 为什么错

模块循环依赖 / 无法单独装卸 / 测试困难。

## ✅ 正确

- 共享组件 → 拆到 core-ui
- 跨 Feature 通信 → 用 EventBus / AppRouter
- Feature 只依赖 Spec(接口)+ core-ui

## lint 状态

- ✅ 静态可检:扫 `feature-*` 模块的依赖声明,出现 `project(":feature-*")` 即报警。
