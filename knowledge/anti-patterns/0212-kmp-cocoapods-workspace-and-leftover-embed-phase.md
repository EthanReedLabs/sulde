---
doc_id: "ap-0212"
container: anti-patterns
platform: ios
summary: "跨平台共享框架改用 CocoaPods 后仍构建 .xcodeproj、保留 embedAndSign phase，或让 App 与共享框架同时链接同一原生依赖，造成模块缺失、重复嵌入/签名冲突或 dyld 初始化 abort"
sedimented_by: auto
---

# 0212 — 跨平台框架 CocoaPods 集成必须走 workspace 且不得与残留 embedAndSign phase 共存

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

把 Kotlin 跨平台共享框架从「直接集成」切换到「CocoaPods 集成」时，只加了 podspec 与 Podfile，却保留了两处旧状态:

1. 构建入口仍指向 `.xcodeproj`:

```bash
xcodebuild -project App.xcodeproj -scheme App build   # ❌ pod 依赖未参与
```

2. App target 里还留着直接集成时代手写的 Run Script phase:

```bash
# ❌ 残留的手动 phase，与 pod 自带的同步脚本重复
cd "$SRCROOT/../shared" && ./gradlew :shared:embedAndSignAppleFrameworkForXcode
```

3. 同一个原生 Pod 已静态进入共享 framework，App target 又直接链接一次：

```text
Shared.framework -> NativeTasksPod
App target       -> NativeTasksPod  # ❌ 两个所有者把同一实现带进最终进程
```

典型症状:`module '<Shared>' not found` / 链接期符号缺失 / `.framework` 被重复嵌入导致签名或产物校验失败 / 增量构建时框架版本时新时旧、clean 后才「好了」。

## 为什么

- **两种集成模式是互斥的**。直接集成靠 Xcode target 里的 `embedAndSignAppleFrameworkForXcode` phase 亲自构建并嵌入框架;CocoaPods 集成靠 `pod install` 生成的 pod target 与其自带脚本完成同一件事。两者同时存在 = 同一个 framework 由两条互不知情的链路各产出一份。
- **产物竞争无固定胜负**。谁后写入谁覆盖，取决于 build phase 顺序与增量构建的跳过策略;因此故障表现为「时好时坏、clean 就好」，最容易被误判为缓存问题而不是配置冲突。
- **CocoaPods 的依赖关系只存在于 workspace**。`pod install` 把 Pods 工程与 App 工程组合进 `.xcworkspace`;直接构建 `.xcodeproj` 时 pod target 根本不在依赖图里，共享模块的 modulemap / 头文件 / 库搜索路径全部缺失——报错在编译或链接期，离真正的根因（构建入口选错）很远。
- **手动 phase 依赖 Xcode 注入的环境变量**（配置、架构、产物目录等）。在 pod 驱动的构建上下文里这些变量含义已变，它可能"成功"地把一个架构或配置不匹配的框架塞进产物，错误推迟到运行期或上架校验才暴露。
- **静态原生依赖只能有一个链接所有者**。App 和共享 framework 同时带入同一实现时，
  ObjC class/category、全局注册器或静态初始化代码会重复出现；构建可能通过，dyld 初始化
  或注册阶段却直接 abort。它不是“缺库”，继续补 linker flags 只会加重冲突。

## ✅ 正确

- **二选一，并写进构建文档**:要么直接集成（保留 embedAndSign phase，构建 `.xcodeproj`），要么 CocoaPods 集成（删除该 phase，构建 `.xcworkspace`）。不存在"两个都留着更保险"。
- 切换到 CocoaPods 集成时，迁移清单逐项执行:
  1. 从 App target 的 Build Phases 中**删除**手写的 `embedAndSign...` Run Script（不是禁用、不是留注释）;
  2. 同时清掉它引入的自定义 Framework Search Paths / Embed Frameworks 条目;
  3. `pod install` 后，所有本地与 CI 构建入口统一改为 `-workspace App.xcworkspace`;
  4. 首次切换后 clean build 一次，确认框架只被嵌入一份。
- 若原生依赖由共享 framework 拥有，App target 必须移除对它的直接链接。Pods 配置由生成
  流程反复覆盖时，在 Podfile `post_install` 中针对 App target 删除对应 linker/search
  flags，并把原因写入注释；禁止手改 `Pods/` 生成产物。
- **CI 上加防回归断言**，比人工检查可靠:
  - 断言构建命令不含 `-project`（或强制模板只暴露 `-workspace` 入口）;
  - 断言工程文件中不再出现手动 embed 脚本的特征串;
  - 断言产物 `Frameworks/` 下共享框架只有一份、架构与配置符合预期。
  - 检查 link map / 最终二进制，确认同一原生实现只有一个所有者，关键 ObjC class 与
    注册符号没有重复来源。
- 团队里若同时有"直接集成"和"CocoaPods 集成"两套历史工程，README 顶部注明本仓库属于哪一种;跨仓库复制构建命令是本坑最常见的引入途径。

## lint 状态

- ❌ 源码级 grep 无法覆盖:冲突同时存在于工程配置文件与外部构建命令中。
- 可自动化的三类断言:(1) 构建脚本/CI 配置中禁止对该工程使用 `-project`;(2) 工程文件中禁止出现手动 embed 脚本特征串;(3) App 与共享 framework 不得同时声明同一原生实现。任一命中即阻断。
