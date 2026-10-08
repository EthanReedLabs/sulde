---
doc_id: "ap-0233"
container: anti-patterns
platform: ios
summary: "Kotlin 多模块或 KMP 工程对同一依赖族使用不同版本，公共代码可能编译通过，却在 Kotlin/Native 链接或 iOS 运行期因 ABI/符号不一致抛 IrLinkageError"
related: [ap-0212, ap-0214]
sedimented_by: auto
---

# 0233 — Kotlin 多模块依赖版本漂移在原生侧表现为 IrLinkageError

- **平台**：Kotlin Multiplatform / Kotlin/Native iOS
- **复发次数**：0

## ❌ 错误

多个模块各自声明同一依赖族，却没有统一版本约束：

```kotlin
// feature-a
implementation("org.example:navigation-compose:2.x")

// feature-b / shared
implementation("org.example:lifecycle-runtime:1.x") // ❌ 与上游期望的 ABI 代际不同
```

JVM/common 编译可能全部通过，直到链接 iOS framework 或真机进入相关路径才出现
`IrLinkageError`、找不到函数/构造器符号或桥接层异常。此时继续排查业务状态和 Swift UI
通常只会远离根因。

## 为什么

- Gradle 可以在不同 source set 和模块里解析出表面可编译的图，但 Kotlin/Native 最终要
  把所有 klib 元数据和原生符号收敛到一个 framework；依赖族的 ABI 不一致会在更晚阶段
  才暴露。
- 错误栈往往指向调用点或生成桥接代码，而不是最早声明旧版本的模块，因此看起来像原生
  构造器、依赖注入或 Compose 生命周期 bug。
- 单模块测试只覆盖自己的解析图，无法证明聚合 framework 的最终依赖闭包一致。

## ✅ 正确

1. 同一依赖族只在 version catalog、平台 BOM 或根约束中声明版本，各模块只引用 alias。
2. 对聚合入口运行 `dependencyInsight`，分别检查 common、iOS source set 与 framework
   link 配置，不能只看某个 feature 的 compile classpath。
3. 升级 navigation、lifecycle、savedstate、DI/Compose 适配层时作为一个兼容单元评审，
   禁止只升报错栈最上方的单个 artifact。
4. 统一版本后清理旧 klib/Gradle 缓存，重链 framework，并在真机触发原故障路径。
5. CI 增加依赖收敛报告：同一 group/兼容族出现多个未批准版本即失败；随后执行 iOS
   framework link smoke，而不止 JVM 单测。

若错误只在 Compose 的 ViewModel 注入路径出现，可把 `koinViewModel` 临时换成
`koinInject` 做**诊断隔离**：前者会带入 `lifecycle-viewmodel-compose` / savedstate 适配层，
后者绕开该生命周期桥。替换后错误消失，说明故障面在依赖列车或 ViewModel 适配层，而非
业务 ViewModel 构造本身；它不等于最终修复。最终仍应对齐 navigation、lifecycle、
savedstate、Koin/Compose 适配版本，或明确实现受支持的生命周期所有权，不能长期用绕行
掩盖 ABI 漂移。

## lint 状态

- ✅ 可检：解析依赖图后按 group/兼容族聚合版本，发现未列入例外清单的多版本即阻断。
- ⚠️ 需维护兼容矩阵：不同 artifact 名可能属于同一发布列车，不能只按完整坐标字符串比较。
- ⚠️ `koinViewModel` → `koinInject` 只允许作为诊断 A/B；若长期保留，必须证明生命周期、
  saved state 与清理语义没有退化。
- ❌ 源码 grep 不足以证明：最终版本由 catalog、约束、传递依赖和 source set 共同决定。
