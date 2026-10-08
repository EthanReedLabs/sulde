---
doc_id: "ap-0187"
container: anti-patterns
platform: android
summary: "切换 Gradle 属性重新构建后布尔开关行为不变、像改了没生效——BuildConfig 常量在编译期被内联,增量缓存把旧值烙死在调用点"
sedimented_by: auto
---

# 0187 — BuildConfig 布尔常量编译期内联,增量缓存烙死旧值

- **平台**:Android

## ❌ 错误

把 BuildConfig 布尔常量当作可随 Gradle 属性切换的运行时开关:改完属性(gradle.properties / `-P` 参数)后直接增量构建,期望所有读取该开关的调用点拿到新值。实际部分或全部调用点仍按旧值执行,且无任何编译报错。

## 为什么

- BuildConfig 字段是 `static final` 编译期常量,Kotlin/Java 编译器会把它**内联进每个调用点的字节码**,调用点从此不再真正引用 BuildConfig 类。
- 切换 Gradle 属性只重新生成 BuildConfig 源文件;若增量编译/构建缓存判定调用方类"未变化"而跳过重编,旧的内联值就被烙死在那些调用点。
- 表现为"改了属性没生效",且不同模块/类可能新旧值混杂,极易误判为业务逻辑 bug。

## ✅ 正确

- 需要跨构建变体/属性切换可靠读取的开关,不依赖编译期常量内联:改走**运行时读取**(反射读 BuildConfig 字段、资源或 manifest metadata、非常量的运行时配置类)。
- 或让编译任务对该属性**显式失效**:把该 Gradle 属性注册为编译/生成任务的输入,属性变化即触发所有依赖方重编;不确定缓存状态时 clean 后全量构建验证。
- 排查判据:"切了属性行为不变"时,先反编译或打印调用点实际读到的值,确认是否为内联旧值,再谈逻辑 bug。
