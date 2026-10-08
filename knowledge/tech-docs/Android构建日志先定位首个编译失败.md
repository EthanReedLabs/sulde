---
doc_id: "tech-docs/Android构建日志先定位首个编译失败"
container: tech-docs
platform: android
summary: "Android 聚合构建中的 D8/元数据警告可能淹没更早的 Kotlin 编译错误；诊断应先定位首个失败 task，再单独重跑对应 compile/test compile task 获取未经后续噪声稀释的根因。"
sedimented_by: auto
---

# Android 构建日志先定位首个编译失败

聚合 Gradle 构建失败时，末尾出现的 D8、metadata 或 dependency 警告不一定是根因。先从
完整日志定位第一个 `FAILED` task 和第一段 compiler `error:`，再对该模块单独运行对应的
`compile*Kotlin`、`compile*UnitTestKotlin` 或 `compile*AndroidTestKotlin`，使用 `--stacktrace`
并保留完整输出。

只有定向编译通过后才继续处理 D8/dex 阶段；禁止根据日志最后几十行直接修依赖。门禁报告
同时列 `first_failed_task`、`first_compiler_error` 与最终失败阶段，避免 warning 数量压过
控制流顺序。fixture 应包含“前段 Kotlin error + 后段大量 D8 warning”，并断言诊断仍指向
Kotlin 源码与首个失败 task。
