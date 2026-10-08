---
doc_id: "ap-0215"
container: anti-patterns
platform: ios
summary: "已弃用：静态 Pod 传递依赖与 Kotlin/Native linker 的技术真值已合并至 ap-0214"
related: [ap-0214]
status: deprecated
canonical: ap-0214
deprecated_at: "2026-08-11"
---

# NNNN — 已弃用：静态 Pod 的传递依赖不会自动传给 Kotlin/Native linker

> **Deprecated / tombstone**：本页仅保留旧 `doc_id` 与路径，兼容历史任务书、链接和
> 检索引用；不得继续作为技术真值维护。

当前唯一真值：

- [`ap-0214 — 静态库 Pod 的传递依赖不会自动进入 Kotlin/Native 链接命令行`](0214-static-pod-transitive-deps-missing-in-kn-linkeropts.md)

原条目的错误信号、CocoaPods/Xcode 与 Kotlin/Native 链路边界、显式 `linkerOpts`、
运行时注册 archive 的 `-force_load`、App bundle 资源打包、产物符号断言及依赖升级
清单均已迁入 `ap-0214`。后续更新只写主条目。
