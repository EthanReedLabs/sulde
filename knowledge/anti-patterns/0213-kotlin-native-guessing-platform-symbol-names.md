---
doc_id: "ap-0213"
container: anti-patterns
platform: cross
summary: "Kotlin/Native 侧引用平台或第三方框架符号时凭 Swift 文档/记忆写名字，编译期报 unresolved reference 或命中同名异义符号"
related: [ap-0160]
sedimented_by: auto
---

# NNNN — Kotlin/Native 平台 API 符号名靠猜而不反查 klib 真实导出名

- **平台**:跨端(Kotlin/Native,含 KMP 的 Apple target)

## ❌ 错误

在 Kotlin/Native 源集里调用系统框架或第三方 native 库时,照着 Swift 官方文档、示例代码或记忆里的驼峰名直接写 Kotlin 符号:

```kotlin
// 按 Swift 文档里的 HKAuthorizationStatus.sharingAuthorized 心算映射
if (store.authorizationStatusForType(type) == HKAuthorizationStatus.sharingAuthorized) { ... }

// 按 Swift 的 RunningMode.liveStream 心算映射
options.runningMode = RunningMode.LIVE_STREAM
```

然后靠「编译一次看报什么错」来试名字,一轮轮改一轮轮编译。

## 为什么错

- Kotlin 侧看到的不是 Swift API,而是 **ObjC/C 头文件经 cinterop 映射后的产物**。Swift 层的嵌套 case、命名空间简写、`@objc(...)` / `NS_SWIFT_NAME` 重命名等语法糖在 ObjC 头里并不存在。
- ObjC 的 `NS_ENUM` 常量通常被**平坦化成顶层常量**(形如 `HKAuthorizationStatusSharingAuthorized`),而不是 Kotlin 枚举的 `Enum.CASE`;`NS_OPTIONS`、typedef 枚举、纯 C 宏各有不同映射结果。
- 第三方 native 库还会带自己的类前缀与工厂式访问器(形如 `MPPRunningMode.byValue(...)`),Swift 侧的简洁写法在 klib 里根本没有对应符号。
- 猜名字的代价不对称:**Kotlin/Native 编译慢**,每猜错一次就是一轮长编译;更糟的情况是猜中了一个同名但语义不同的符号,编译通过而行为错误,把问题推迟到运行时。
- 文档名 → 导出名之间**没有可靠的心算规则**,所以「我大概记得叫什么」在这里永远是二手线索,不是真值。

## ✅ 正确

**改代码前先反查真实导出名,拿到一手证据再写。**

1. 对平台框架,直接 dump 对应 target 的 platform klib:

```bash
# platform klib 通常在 Kotlin/Native 的本地工具链目录下,按 target 分目录
find "$HOME/.konan" -name '*.klib' -path '*platform*' | grep -i <framework>
klib dump <path-to>.klib | grep -i '<关键词>'
```

2. 对第三方 native 依赖,dump 它的 cinterop/klib 产物,或直接 grep 随包分发的头文件:

```bash
klib dump <interop>.klib | grep -i '<关键词>'
grep -rn '<关键词>' <framework>.framework/Headers/
```

3. dump 不可用时退化为二进制符号扫描:

```bash
nm -gU <binary> | grep -i '<关键词>'
strings <binary> | grep -i '<关键词>'
```

4. IDE 自动补全在交互环境下也算一手证据,但 headless / CI / 远程执行环境下以 `klib dump` 输出为准——补全不可用时不要退回「凭印象写」。
5. 把查到的符号名连同**来源命令与输出片段**记进改动说明,下次同一框架的其他符号可以直接沿用同一条反查路径。

## lint 状态

- ⚠️ 难以静态检测:名字猜错通常表现为编译失败,lint 抓不到「猜」这个行为本身。
- 可执行的约束在 review 侧:引用平台/第三方 native 符号的改动,要求附带反查证据(dump 命令 + 命中行),而不是「编过了」。

## How to apply

- 把「查符号名」当成独立的前置步骤,和「写代码」分开;不要把长编译当搜索引擎用。
- 跨端项目在 native interop 层沉淀一份「已反查符号清单」,新符号进清单前先 dump。
- 遇到 unresolved reference 时,第一反应是 dump klib,而不是换一个拼法再编一次。

## 关联

- 同属 Kotlin/Native interop 系列的另一类问题:C/Objective-C variadic API 的 ABI 装箱(那类是编译通过、运行时崩溃;本条是名字层面的编译期问题)。
