---
doc_id: "ap-0214"
container: anti-patterns
platform: ios
summary: "Kotlin/Native 通过 CocoaPods 引入静态库 Pod 后，链接期报 undefined symbols，或链接通过但运行时找不到计算图/模型——只声明了 pod 本身，未把传递 framework、运行时注册 archive 与 App bundle 资源显式补入对应链路"
related: [ap-0212]
aliases: [ap-0215]
supersedes: [ap-0215]
sedimented_by: auto
---

# NNNN — 静态库 Pod 的传递依赖不会自动进入 Kotlin/Native 链接命令行

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

在 Kotlin 跨平台工程里用 CocoaPods 插件引入一个**以静态库形式分发**的 Pod（典型如端侧视觉/推理任务库），只声明 pod 本身，就默认它的依赖会像 Xcode target 那样自动传递:

```kotlin
cocoapods {
    // ❌ 只声明主 pod，认为它的依赖 framework 会被自动带上
    pod("VisionTasksPod")
    // 缺: 依赖的 Common framework、其搜索路径、以及计算图归档资源
}

binaries.all {
    // ❌ 只写主 framework，依然假设伴生库与注册 archive 会自动传递
    linkerOpts("-framework", "VisionTasks")
}
```

典型症状分两种，且**往往不同时出现**:

1. 链接期:`Undefined symbols for architecture arm64` —— 缺失符号属于主 pod 的**依赖库**（Common/Core 之类），不是主 pod 自己;
2. 链接期完全正常，**运行时**初始化失败:找不到该库随包分发的计算图归档 / 模型资源（`graph`、`.binarypb`、task bundle 之类）。

常见的错误应对是反复 `pod install`、清缓存、改版本号——这些都不触及根因。

## 为什么

- **两条链接链路的依赖展开范围不同**。CocoaPods 面向 Xcode target 时会展开完整依赖图，把传递依赖的 framework、`-l`、搜索路径注入到 target 的链接参数里;而 Kotlin/Native 的 cinterop 与 link 阶段只消费「该 pod 自身的 vendored 产物」+「Gradle DSL 里显式声明的 `linkerOpts`」。**传递依赖不会自动出现在 K/N 的链接命令行上**。
- **静态库没有运行期兜底**。动态 framework 的未决符号可以推迟到运行时由 dyld 解析，漏配可能一路蒙混到启动;静态库要求所有符号在链接期解析完毕，所以同一处漏配在静态分发下会**立刻**炸在 linker 上。这也是为什么同样的写法换个动态分发的 pod 就「没问题」，从而给出错误的经验归纳。
- **资源型产物根本不是符号**。计算图归档、模型文件、task bundle 这类东西 linker 不关心，漏了不会有任何链接期告警;故障被推迟到运行时首次初始化推理引擎才暴露，离根因（打包配置）很远，极易误判成模型文件损坏或路径 bug。
- **只被运行时注册机制引用的静态 archive 会被 linker 丢弃**。某些 SDK 把算子注册表或预编译计算图封在独立 `.a` 中，没有普通静态调用点；仅增加 `-L` 或普通 `-l` 不保证目标文件被保留。这类链接输入与前一条 App bundle 资源不是同一种产物，不能用“已打包资源”替代 linker 保活。
- **分发形态是 pod 作者的选择，不写在你的代码里**。同一个库的不同版本可能在静态/动态之间切换，`use_frameworks!` 的 linkage 设置也会改变结果。因此「上次这么写能过」不构成任何保证。

## ✅ 正确

- **先确认分发形态**:看 podspec 里是 `vendored_frameworks`（动态）还是 `vendored_libraries` / 静态 xcframework，以及 Podfile 的 `use_frameworks! :linkage => :static`。静态即进入本条的排查清单。
- **把传递依赖显式补进 K/N 的链接参数**，缺一项补一项，不要指望自动传递:

```kotlin
cocoapods {
    pod("VisionTasksPod")
    pod("VisionTasksCommonPod")   // 依赖也显式声明
}

iosArm64 {
    binaries.all {
        linkerOpts(
            "-F", "<依赖 framework 所在目录>",
            "-L", "<依赖 library 所在目录>",
            "-framework", "VisionTasks",
            "-framework", "VisionTasksCommon",   // 显式补依赖 framework
            "-force_load", "<archive 目录>/graph_bundle.a", // 保留运行时注册符号
        )
    }
}
```

- **运行时注册 archive 走链接链路**:优先用 `-force_load` 精确保活单个 `.a`；普通搜索路径不足以阻止 dead-strip，也不要默认用全局 `-all_load`，以免引入重复符号或无谓增大包体。
- **按归档所有权选择保活强度**：先用 `file`/`nm` 确认 framework binary 是静态 archive
  还是动态 Mach-O。只有静态 archive 才进入 `-force_load`/`-u` 选择：
  - 归档主要由 category、注册器和无直接引用对象组成，且不存在第二所有者时，可对该
    archive 精确 `-force_load`；
  - 大型归档已知含可能重复的实现时，优先 `-u <registration_anchor_symbol>` 只拉入包含
    锚点的 object，再用 `nm` 确认注册符号到位；
  - 已由另一个 framework 拥有相同实现的输入保持普通链接，禁止两边同时全量
    `-force_load`。`-ObjC` 只能帮助 ObjC class/category，不保证 C++ 静态注册对象被保留。
- **App bundle 资源单独走打包链路**:计算图文件、模型文件与 task bundle 必须显式加入最终 App bundle，并在运行时用「文件存在 + 引擎成功加载」双条件判 ready，不能只判文件存在。
- **一次性把依赖列全**:以 podspec 的 `dependency` 段为准逐条对照，而不是「报什么符号补什么 framework」——后者是逐个试错，补到不报错为止时往往还漏着只在某条运行路径上用到的依赖。
- **依赖升级清单**:新增或升级 Pod 时重新读取 podspec 的依赖、vendored 产物与资源声明，同步 `linkerOpts` 和资源清单；SDK 小版本也不能沿用旧依赖图。
- **验证方式**:clean 后完整链接一次（增量构建会掩盖漏配）；对最终二进制确认伴生库入口符号和 archive 注册符号确实存在；真机触发推理初始化，覆盖 App bundle 资源只在运行期暴露的分支。
- **CI 加断言**:声明了已知静态 pod，但链接参数缺其依赖 framework/archive、最终二进制缺关键注册符号，或 App bundle 缺必需资源，即阻断。

## lint 状态

- ⚠️ 部分可检:维护一张「已知静态分发 pod → 必需 framework / archive / App bundle 资源」映射表，扫描 pod 声明、`linkerOpts` 与资源清单的差集，缺项即报警。
- ✅ 产物可检:对最终二进制断言伴生库入口符号与运行时注册符号，对 App bundle 断言必需资源清单。
- ✅ 所有权可检：link map 中每个关键实现/注册符号只能有一个来源；使用 `-u` 时锚点和
  它负责的注册项都必须出现在最终二进制。
- ❌ 不可全自动:pod 的分发形态由上游决定且可能随版本变化,映射表需在升级依赖时人工复核。
- 关联:同属跨平台框架与 CocoaPods 集成的配置类坑，但根因不同（另一条是集成模式冲突与构建入口选错，本条是依赖传递范围）。
