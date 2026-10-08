---
doc_id: "ap-0160"
container: anti-patterns
platform: cross
summary: "0160 KMP Kotlin/Native 直接调用 Objective-C variadic API"
related: [ap-0211, ap-0213]
---

# 0160 KMP Kotlin/Native 直接调用 Objective-C variadic API

- **平台**:跨端 + iOS
- **复发次数**:1

## ❌ 错误

KMP 的 `iosMain` 代码直接调用 C/Objective-C 可变参数 API，并认为 Kotlin 值会按
format specifier 自动完成 Objective-C ABI 装箱：

```kotlin
NSLog("source=%@", source)
```

代码可以通过 Kotlin/Native 编译，但真机在 Foundation 格式化阶段触发
`EXC_BAD_ACCESS`，堆栈常见 `NSLog`、`_NSDescriptionWithStringProxyFunc` 和
`objc_opt_respondsToSelector`。业务 API 可能尚未执行，因此容易误判为权限、UIKit
present 时序或内存问题。

## 为什么错

- C variadic 参数没有静态类型元数据；format string 是运行时约定，不是 ABI 转换器。
- Kotlin/Native 暴露一个 native 函数并允许调用，不代表 Kotlin `String`、Boolean、
  数值或 nullable 值会被装箱成 `%@`、`%d` 等期望的 C/Objective-C 类型。
- Foundation 把错误位模式当作 Objective-C 对象后会发送 selector，最终表现为野指针
  崩溃；错误位置通常落在系统格式化函数而不是业务调用点。
- 只看调试启动器的退出 signal 可能丢失真实异常类型，必须读取符号化设备报告。

## ✅ 正确

在 Kotlin 侧先构造完整消息，只跨 native 边界传一个有类型的字符串：

```kotlin
NSLog("source=$source")
```

需要结构化字段、隐私等级或高频日志时，提供 typed Swift/Objective-C bridge，或统一的
单字符串日志 facade；不要在 Kotlin 调用点扩散 C variadic API。

诊断顺序：

1. 从真机拉取并符号化 `.ips`。
2. 若 faulting frames 包含 Foundation format + Objective-C selector dispatch，先审计
   KMP/native variadic 边界。
3. 修复后扫描全部 `iosMain` 同类调用，不只改当前入口。
4. 用原真机交互路径验证，编译通过不能替代运行时 ABI 验证。

## lint 状态

- KMP/iOS ✅ 可用静态 grep 阻止 `NSLog("...%...", value)` 形态。
- ⚠️ 通用 C variadic API 很多，完整检测需要项目维护 allowlist/typed bridge 清单；仅检查
  `NSLog` 不能证明所有 interop 都安全。

## How to apply

- code review 将「Kotlin/Native → C/Objective-C variadic」作为独立分类检查，不归入普通
  UIKit 或权限问题。
- native crash 中同时记录源码语言边界、ABI 类型、设备报告和原始交互步骤。
- 跨端项目的 Apple logging scaffold 默认只暴露单消息或 typed fields API。

## 关联

- UIKit presentation 时序是另一类问题；只有堆栈进入 `presentViewController` 或 transition
  才按 sheet 竞态排查。
