---
doc_id: "ap-0211"
container: anti-patterns
platform: cross
summary: "iOS 侧构建在 Kotlin/Native 生成 ObjC framework 阶段崩溃、报错不指向任何业务代码行时,说明整个模块的 public 面被全量导出"
related: ["ap-0160"]
sedimented_by: auto
---

# KMP Kotlin/Native framework 导出模块内全部 public 声明

- **平台**:跨端 + iOS

## ❌ 错误

共享模块的 `commonMain` / `iosMain` 沿用 Kotlin 默认的 public 可见性,只关心
"Swift 侧能调到入口",内部实现类型、工具类、扩展、data class、sealed 层级、
泛型容器全部保持 public:

```kotlin
// commonMain —— 全部默认 public
data class InternalCacheKey(val raw: String)
sealed class ParseNode { /* ... */ }
class RetryPolicy<T> { /* ... */ }

class FeatureFacade { fun start() { /* Swift 真正需要的只有这一个入口 */ } }
```

症状:`assembleXCFramework` / `linkPodDebugFrameworkIos` 之类的任务失败,编译器在
ObjC export 阶段崩溃或抛内部异常,报错文本里没有具体源文件与行号,重跑、clean、
清缓存都无效;而 `compileKotlinIos` 本身是通过的。容易被误判为编译器 bug、
Gradle 缓存脏或 Xcode 版本不兼容。

## 为什么错

- Kotlin/Native 生成 ObjC framework 时,**导出面不是"Swift 调用到的"而是"模块内所有
  public 声明"**;没有被任何 Swift 代码引用的类型同样会被写进 header。
- ObjC 的类型系统比 Kotlin 窄:泛型型变、sealed/嵌套层级、value class、
  协程与 Flow 相关类型、跨文件同名类型在映射时都可能落到不受支持或名字冲突的构造上。
  public 面越大,踩中其中一个的概率越高。
- 崩溃发生在"从 Kotlin 声明生成 ObjC 声明"这一步,此时已经脱离源码上下文,
  因此错误信息缺少定位信息——**报错点与根因位置天然不重合**,不能按普通编译错读。
- 导出面同时就是二进制 ABI:全量 public 还会放大 framework 体积,并让后续任何内部
  重命名都变成对外破坏性变更。

## ✅ 正确

把"对 Swift 可见"当成显式白名单,而不是默认值:

```kotlin
// commonMain —— 默认 internal
internal data class InternalCacheKey(val raw: String)
internal sealed class ParseNode { /* ... */ }
internal class RetryPolicy<T> { /* ... */ }

// 只有 Swift 入口是 public,且只用 ObjC 能干净映射的类型
class FeatureFacade {
    fun start() { /* ... */ }
}
```

规则:

1. 共享模块默认 `internal`,只把 Swift 真正调用的入口显式声明 public。
2. 入口做成**最小 facade**:少量类型、平坦参数与返回值(基础类型、字符串、
   简单 data class、回调),不把泛型容器、sealed 层级、并发原语暴露到边界上。
3. 已经踩坑时按导出面二分收敛:批量把可疑区域改 internal,构建通过后再逐块放回,
   定位到具体触发映射失败的声明——比读崩溃堆栈快得多。
4. 新增 public 声明视同新增对外 API,走与接口变更同级的评审。

## lint 状态

- ✅ 可静态检查:统计共享模块中未标 `internal` 的顶层声明数量,超过白名单规模即报警。
- ⚠️ 无法静态判定某个 public 声明是否会导致 ObjC 映射失败,只能约束导出面大小。
- CI:把 framework 生成任务(而不仅是 Kotlin 编译)纳入必跑,否则该类崩溃会推迟到
  iOS 侧集成时才暴露。

## 关联

- 同属"Kotlin/Native 与 Objective-C 边界"系列:另一类是调用侧的 ABI 问题
  (C variadic 参数装箱),表现为运行时崩溃而非构建期崩溃,见 ap-0160。
