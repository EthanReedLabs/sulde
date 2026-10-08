---
doc_id: "tech-docs/案例研究/02-iOS-TCA架构实践/TCA依赖注入scope错配与占位值"
container: case-studies
platform: none
summary: "**技术域**：iOS 架构 / Swift / The Composable Architecture / swif…"
related: [ap-0210]
---

# TCA 依赖注入 Scope 错配与占位值案例研究

> **技术域**：iOS 架构 / Swift / The Composable Architecture / swift-dependencies
> **难度**：⭐⭐⭐⭐⭐
> **关键词**：TCA / swift-dependencies / @Dependency / DependencyValues / DependencyKey / liveValue / testValue / previewValue / prepareDependencies / withDependencies / SwiftUI View
> **可迁移场景**：TCA 模块化应用、SwiftUI View 直接订阅 dependency、跨 Reducer 与 View 共享会话状态、单一事实源迁移、依赖注入 scope 治理

---

## 场景与系统架构

某 iOS 应用使用 SwiftUI + TCA 构建页面和状态流，依赖注入由 `swift-dependencies` 管理。业务里有一个会话依赖，负责提供当前登录态、积分、会员信息和状态流。正确预期是：网络请求成功后，Reducer 更新会话依赖中的存储，SwiftUI View 订阅同一条状态流，最终把积分和会员标识显示到页面上。

问题出现在一次单一事实源迁移后：页面不再只从 Feature State 读取积分，而是让 SwiftUI View 里的一个展示组件直接通过 `@Dependency` 订阅会话状态流。这样做本身符合“会话状态集中化”的方向，但它改变了依赖读取的位置：从 reducer scope 内读取，变成 SwiftUI View 直接读取。

### TCA 模块结构图

```
App Startup
├── Root Store
│   ├── RootFeature
│   │   ├── SomeFeature
│   │   │   ├── reducer action：刷新积分 / 会员信息
│   │   │   └── state：页面业务状态
│   │   └── ChildFeature
│   └── withDependencies { ... }      // 修复前：只覆盖 reducer tree
│
├── DependencyValues
│   └── sessionClient
│       ├── liveValue                 // 生产默认实现
│       ├── testValue                 // 测试占位或可控实现
│       └── previewValue              // 预览占位或轻量实现
│
└── SwiftUI View Tree
    ├── SomeView
    │   └── ValueBadge
    │       └── @Dependency(\.sessionClient)
    └── 直接订阅 sessionStream()
```

修复前的关键结构是：依赖注册写在创建 `Store` 的 `withDependencies` 闭包里。这个覆盖对 TCA 的 reducer tree 生效，但 SwiftUI View 本身不属于 reducer tree。于是 Reducer 和 View 虽然都写了 `@Dependency(\.sessionClient)`，实际拿到的却不是同一个依赖实例。

---

## 问题现象

用户可见现象集中在个人资料页：

1. 积分区域一直显示 `0`。
2. 会员标识一直显示默认的 `FREE`。
3. 多次刷新后页面仍不更新。

运行日志反而显示接口链路正常：

```text
getCurrentCredits SUCCESS  credits=500
getMembershipDetail SUCCESS
连续多帧 SUCCESS，未观察到 FAIL
```

也就是说，最初怀疑的“网络请求失败 / 错误被吞 / 本地持久化未写入”并不成立。可观测事实是：

| 链路 | 观测结果 |
|---|---|
| 积分接口 | 成功返回，积分值为 500 |
| 会员接口 | 成功返回 |
| 写入会话存储 | 已执行 |
| 本地持久化 | 已写入 |
| 状态广播 | 已触发 |
| SwiftUI 展示 | 仍显示积分 0 和默认会员标识 |

这类现象的关键判断是：数据生产链路已经成功，但 UI 消费链路没有收到同一个状态源的更新。

---

## 根因分析

### 表层根因：Reducer 和 SwiftUI View 读到了不同的 dependency scope

故障链路可以简化为两列：

```
Reducer 端                                      SwiftUI View 端
────────────────────────────────────            ────────────────────────────────────
@Dependency(\.sessionClient)                     @Dependency(\.sessionClient)
        │                                                │
        ▼                                                ▼
Store.withDependencies 注入的真实实现              DependencyKey.liveValue 默认实现
        │                                                │
        ▼                                                ▼
写入真实会话存储：credits = 500                   订阅占位 sessionStream()
        │                                                │
        ▼                                                ▼
broadcast() 向真实订阅者发送更新                  stream 立即结束或没有有效 emit
        │                                                │
        ▼                                                ▼
Reducer scope 内数据正确                           View 显示默认值：0 / FREE
```

这不是普通的异步刷新慢，也不是网络层失败，而是依赖注入的作用域错配。Reducer 里的 `@Dependency` 受 `Store.withDependencies` 覆盖；SwiftUI View 里的 `@Dependency` 不在这个 reducer scope 内，因此读取了根 `DependencyValues` 上的默认值。

### swift-dependencies 的解析机制

在 `swift-dependencies` 中，一个 dependency 通常通过 `DependencyKey` 定义：

```swift
private enum SessionClientKey: DependencyKey {
    static let liveValue = SessionClient(
        currentSync: { .signedOut },
        sessionStream: { AsyncStream { continuation in
            continuation.finish()
        } },
        setCredits: { _ in }
    )

    static let testValue = SessionClient.unimplemented
    static let previewValue = SessionClient.preview
}

extension DependencyValues {
    var sessionClient: SessionClient {
        get { self[SessionClientKey.self] }
        set { self[SessionClientKey.self] = newValue }
    }
}
```

`liveValue`、`testValue`、`previewValue` 是公共框架语义下的不同默认值来源：

| 值 | 典型用途 | 风险点 |
|---|---|---|
| `liveValue` | 生产环境默认实现 | 如果项目把它写成 placeholder，而真实实现只在局部覆盖，就可能被非覆盖 scope 读到 |
| `testValue` | 测试环境实现或未实现占位 | 适合暴露测试中未注入依赖的问题 |
| `previewValue` | SwiftUI Preview 使用 | 通常是轻量或静态数据 |

本案例里的 `liveValue` 是一个安全占位实现：同步读取返回 signed-out，状态流立即结束，写入方法 no-op。它作为默认值本身没有问题；问题是 SwiftUI View 在生产运行时不应该读到这个占位实现。

### `withDependencies` 的传播边界

修复前，依赖注册大致写在 Store 构造处：

```swift
let store = Store(initialState: RootFeature.State()) {
    RootFeature()
} withDependencies: {
    $0.sessionClient = .live()
}
```

这段代码容易给人一个错觉：既然 Root Store 已经注入了真实 `.live()`，整个 App 都应该拿到它。实际不是这样。

`Store(... ) { ... } withDependencies: { ... }` 覆盖的是这个 Store 的 reducer 执行环境。也就是说，`RootFeature` 以及通过 reducer composition 进入的 child reducer，在处理 action、effect、dependency 读取时会看到这个 override。但 SwiftUI View 的 `body`、`.task`、`ObservableObject` 或独立 View 组件中的 `@Dependency`，并不会自动进入这个 Store 的 reducer dependency context。

因此下面两处代码虽然形式相同，解析路径不同：

```swift
// reducer 内：命中 Store.withDependencies 覆盖
struct SomeFeature: Reducer {
    @Dependency(\.sessionClient) var sessionClient
}

// SwiftUI View 内：不在 reducer scope，读取当前全局 DependencyValues
struct ValueBadge: View {
    @Dependency(\.sessionClient) var sessionClient
}
```

### `@Dependency` 的注入时机

`@Dependency` 不是传统意义上“运行到某行代码再从 Store 取一次依赖”。它会基于当前 `DependencyValues` 上下文解析依赖。Reducer 执行时，TCA 会在 reducer scope 中设置对应的 dependency values；View 初始化、`body` 求值或 `.task` 执行时，如果外层没有全局准备或显式覆盖，就会回落到根 dependency values。

这解释了为什么接口、存储、广播都正常，但 UI 永远不更新：数据写入发生在 reducer scope 的真实实现里；View 订阅发生在根 scope 的占位实现里。两条链路没有共享同一个存储实例，也没有共享同一个 `AsyncStream` 订阅者列表。

### 值类型依赖放大了这个问题

会话依赖通常会被建模为 struct，内部字段是 closure：

```swift
struct SessionClient {
    var currentSync: () -> Session
    var sessionStream: () -> AsyncStream<Session>
    var setCredits: (Int) -> Void
}
```

struct 是值类型。不同 scope 解析出的 `SessionClient` 会复制不同的 closure 集合；这些 closure 捕获的底层 store 也可能完全不同。Reducer 端的 `.live()` 捕获真实存储，View 端的 `liveValue` 捕获占位流，于是广播链断开：

```
setCredits(500)
└── 写入真实 store
    └── broadcast 给真实 store 的订阅者

ValueBadge.sessionStream()
└── 订阅的是 placeholder stream
    └── 没有收到真实 store 的 broadcast
```

### 为什么迁移前没有暴露

在迁移前，积分字段位于 Feature State 中。刷新动作在 reducer 内执行，`@Dependency` 也在 reducer scope 内读取，因此能命中 Store 注入的真实依赖。SwiftUI View 只是展示 `state.credits`，并不直接读取 dependency。

迁移后，积分和会员状态下沉到会话依赖，View 组件直接订阅 `sessionStream()`。这是第一次让 SwiftUI View 成为 dependency consumer，也就第一次暴露出“Store scope 覆盖不等于 View tree 全局覆盖”的差异。

---

## 解决方案

### 方案：用 `prepareDependencies` 做进程级依赖准备

修复方式是把真实依赖注册从 Store 局部 scope 提升到应用启动阶段的全局 dependency preparation：

```swift
prepareDependencies {
    $0.sessionClient = .live()
}

let store = Store(initialState: RootFeature.State()) {
    RootFeature()
}
```

`prepareDependencies` 是 `swift-dependencies` 提供的全局准备 API。它适合注册生产环境中需要被 reducer、SwiftUI View、adapter、service 等多种调用点共同读取的依赖。这样一来，Reducer 和 View 内的 `@Dependency(\.sessionClient)` 都会解析到同一份真实实现。

修复后的依赖链路变成：

```
App Startup
└── prepareDependencies { sessionClient = .live() }
    ├── Reducer @Dependency(\.sessionClient)
    │   └── 写入真实会话存储
    ├── SwiftUI View @Dependency(\.sessionClient)
    │   └── 订阅真实 sessionStream()
    └── 其他适配层 @Dependency(\.sessionClient)
        └── 读取同一份会话状态源
```

### 验证结果

修复后可观测结果：

1. 编译通过。
2. 进入个人资料页后，积分从 `0` 正确显示为接口返回的 `500`。
3. 会员标识从默认值恢复为真实状态。
4. 临时诊断日志移除后，仍通过 UI 行为完成验证。

### 为什么这样修，而不是其他做法

**不选择继续修接口或 decode 逻辑**：日志已经证明接口连续成功，积分返回值为 500，写入和广播也执行了。继续沿网络层排查会偏离事实。

**不选择把 `try?` 全部替换成显式错误处理作为主修复**：显式错误处理可以提升可观测性，但本次 UI 不更新不是错误被吞导致的。它不能解决 View 读到 placeholder dependency 的问题。

**不选择把积分重新放回 Feature State**：这能绕开 View 直接读取 dependency 的问题，但会倒退到多份状态源，破坏会话状态集中化目标。真正的问题是依赖 scope 错配，而不是单一事实源本身错误。

**不选择在每个 SwiftUI View 上局部包一层依赖覆盖**：局部覆盖容易遗漏新组件，也会让依赖拓扑分散。会话依赖属于进程级共享资源，应该在应用启动阶段统一准备。

**不选择把 `liveValue` 改成真实 `.live()` 来兜底**：这会让默认值带上真实副作用，测试、Preview 和未显式注入场景更难控制。更好的做法是保留默认值的安全性，同时在生产启动路径显式 `prepareDependencies`。

### 防御手段：限制生产代码中的 Store-scoped 全局依赖

可以增加静态检查，拦截生产代码中用 `Store(... ) withDependencies:` 注册全局共享依赖的模式：

```bash
hits=$(grep -rEHn 'Store\(.*\) *\{[^}]*\} *withDependencies:' Sources/ 2>/dev/null \
  | grep -vE "Test/|Tests/|Preview" || true)

if [ -n "$hits" ]; then
  echo "Store-scoped withDependencies may not reach SwiftUI View @Dependency consumers."
  echo "Use prepareDependencies for process-wide shared dependencies."
  echo "$hits"
  exit 1
fi
```

这类检查不应禁止所有 `withDependencies`。它仍然适合测试、Preview、局部 reducer 覆盖和临时替身。需要拦截的是“生产共享依赖误放在 Store scope，实际又被 SwiftUI View 直接读取”的高风险组合。

---

## 可迁移原则

### 1. 依赖注入必须画出 consumer 边界

同一个 `@Dependency` key 可能被 reducer、SwiftUI View、service、adapter、test harness 读取。注册依赖前先确认 consumer 在哪个 scope：只给 reducer 用，可以放在 Store scope；给 View 和 reducer 共同用，应使用更上层的全局准备或显式环境包裹。

### 2. 默认 `liveValue` 不应承担生产兜底职责

`liveValue` 可以是安全占位，也可以是真实实现，取决于项目策略。但只要真实依赖需要共享实例、持有状态或产生副作用，就不应依赖“某个 scope 没注入时自动读到正确值”的运气。生产启动路径应显式准备依赖。

### 3. 单一事实源迁移会改变依赖读取位置

把状态从 Feature State 下沉到 client/store 后，View 很可能从“展示状态”变成“订阅依赖”。这会改变 dependency scope、订阅生命周期和测试入口。迁移方案必须同步审查 `@Dependency` 出现的位置。

### 4. 日志能证明生产链路成功，也能缩小 UI 消费链路

当接口、持久化、广播都已被日志证明成功时，继续排查网络层收益很低。下一步应检查订阅者是否订阅了同一个实例、同一个 stream、同一个 dependency scope。

### 5. 值类型 client + closure capture 要关注实例身份

Swift 里常见的 client struct 很轻量，但 closure 捕获的底层对象决定了真实行为。两个看起来类型相同的 client，可能因为捕获了不同 store 而完全不互通。排查时要追踪“closure 捕获了谁”，而不是只看 key path 名称是否一致。

---

## 技术深问 Q&A

### Q1：`Store.withDependencies` 是不是不能用了？

不是。它适合给某个 Store 的 reducer tree 提供局部覆盖，例如测试、Preview、某个子模块替换实现。问题是把它误当成全 App 依赖注册。只要 SwiftUI View 也直接用 `@Dependency` 读取同一个 key，Store scope 就不够。

### Q2：为什么 SwiftUI View 里的 `@Dependency` 不自动继承 Root Store 的 dependencies？

Root Store 的 dependencies 是 reducer 执行上下文，不是 SwiftUI 环境值。View tree 和 reducer tree 是两套结构。除非框架或应用显式把 dependency values 放到 View 所在上下文，否则 View 里的 `@Dependency` 会按当前全局 `DependencyValues` 解析。

### Q3：`prepareDependencies` 会不会让测试变难？

不会，但要管理好测试隔离。测试中仍可用 `withDependencies` 或测试工具覆盖依赖。关键是生产入口使用 `prepareDependencies` 注册真实共享依赖，测试入口使用测试专属覆盖，避免测试依赖生产全局状态。

### Q4：为什么不把 `DependencyKey.liveValue` 直接写成真实实现？

如果真实实现持有状态、访问磁盘、发网络请求或注册 stream，把它放进默认 `liveValue` 会让未显式注入的环境也产生副作用。占位默认值更容易暴露 scope 错配；生产路径显式准备真实实现更可控。

### Q5：如何快速判断自己是否遇到了同类问题？

看三个信号：Reducer 日志显示写入成功；View 订阅没有收到任何有效 emit；同一个 dependency key 在 reducer 和 SwiftUI View 中都被读取。如果同时成立，应优先检查依赖注册是否只发生在 `Store.withDependencies`。

### Q6：这种问题和 Android 依赖注入有什么类比？

它类似把本应放在全局或应用级 scope 的依赖注册到了 ViewModel 或页面 scope：页面内某条链路能拿到真实实现，另一个跨 scope consumer 却拿到默认实现或新实例。通用教训是：依赖生命周期必须覆盖所有 consumer 的生命周期。
