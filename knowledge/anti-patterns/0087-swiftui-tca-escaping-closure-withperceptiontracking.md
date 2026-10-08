---
doc_id: "ap-0087"
container: anti-patterns
platform: ios
summary: "SwiftUI + TCA escaping closure 漏 WithPerceptionTracking 五大触…"
---

# 0087 — SwiftUI + TCA escaping closure 漏 WithPerceptionTracking 五大触发点

- **平台**:iOS（Android Compose 是否对应需 audit）
- **复发次数**:3
- **lint 状态**:✅ iOS 软警告（`rules/005-perception-escaping-closure.sh`，存量清零后升硬阻断）
- **runtime 验证**:✅ `verify/check-perception-runtime.sh`（真机 syslog 抓 PerceptionCore subsystem）

## 现象

SwiftUI View 用 `@Perception.Bindable var store: StoreOf<Feature>` + body 顶层 `WithPerceptionTracking { ... }`，运行时仍 log 大量:

```
[PerceptionCore] Perceptible state '\State.xxx' was accessed from a view but is not being tracked.
[PerceptionCore] Perceptible state '\Store<State, Action>.currentState' was accessed from a view but is not being tracked.
```

伴随业务现象:状态变化 → view 不重渲染（modal 不弹 / textfield 不刷新 / 按钮选中态不切换）。

## 根因

`WithPerceptionTracking` 只覆盖**同步**求值阶段。SwiftUI 内部把闭包**存起来延后调用**的所有位置（escaping closure），调用时已超出 tracking scope，Perception 追踪不到。

## 五大触发点 + 修法

| # | 触发点 | grep 模式 | 修法 |
|---|---|---|---|
| 1 | `Binding(get: { store.xxx }, set: { ... })` 用作 `.toast/.sheet/.alert/.fullScreenCover` 的 `isPresented` / `TextField` 的 `text` | `get:[[:space:]]*\{[[:space:]]*(store\|viewStore)\.` | `@State` 镜像变量 + `.onChange(of: store.xxx)` / `.onChange(of: mirrored)` 双向同步，Binding 给 SwiftUI 时只读 `@State` |
| 2 | `.sheet { ... }` / `.fullScreenCover { ... }` / `.popover { ... }` 的 content trailing closure 内读 store | `\.(sheet\|fullScreenCover\|popover)\s*\{` | content 内最外层包一层 `WithPerceptionTracking { ... }` |
| 3 | `ForEach { item in ... store.xxx ... }` / `GeometryReader { proxy in ... }` / `ScrollViewReader { ... }` trailing closure | `ForEach.*\bin$` | trailing closure 内首行加 `WithPerceptionTracking { ... }` |
| 4 | `let store: StoreOf<Feature>` 替代 `@Perception.Bindable var store` 的子 view | `^\s*let\s+store:\s*StoreOf<` | 改 `@Perception.Bindable var store`（`let` 模式 SwiftUI 不知道字段是 Perceptible） |
| 5 | `.overlay { if cond { ... store.xxx ... } }` / `.background { ... }` 的 ViewBuilder closure 内访问 store | `\.(overlay\|background)\s*\{` 附近有 store | overlay/background 内**条件分支**包 `WithPerceptionTracking { ... }` |

## 例外清单（豁免）

- `UIViewControllerRepresentable` struct 内的 `let store: StoreOf<F>`（UIKit bridge 不渲染 SwiftUI body，状态变化走 `updateUIViewController`）— 加行尾 `// noqa: perception`
- `Binding(get:set:)` 内只调用 `store.send(...)` 不读 state 字段 — 可豁免（`send` 不触发 Perception 追踪）

## 修法模板（Binding → @State 镜像）

❌ 错误:

```swift
.toast(
    isPresented: Binding(
        get: { store.showError },
        set: { if !$0 { store.send(.dismissError) } }
    ),
    message: store.errorMessage ?? ""
)
```

✅ 正确:

```swift
@State private var showError = false
@State private var errorText = ""

// body 内 WithPerceptionTracking { } 顶层:
.toast(isPresented: $showError, message: errorText)
.onChange(of: store.showError) { newValue in
    if showError != newValue { showError = newValue }
}
.onChange(of: showError) { visible in
    if !visible && store.showError { store.send(.dismissError) }
}
.onChange(of: store.errorMessage) { newValue in
    errorText = newValue ?? ""
}
```

## 防御机制

| 层 | 工具 |
|---|---|
| commit 前 lint | `rules/005-perception-escaping-closure.sh`（pre-commit 自动跑） |
| 真机 runtime 验证 | `verify/check-perception-runtime.sh [seconds] [udid]`（完工三步可加为第 4 步） |
| 协调端 task md 自检 | 涉及 `.sheet/.fullScreenCover/.overlay/Binding(get:set:)/ForEach trailing closure` 内读 store？写 task md 审单加此问 |

## noqa 临时豁免 vs 真修

当 Binding 模式分布广（如几十处），可先统一加 `// noqa: perception` 让 lint 归零，标记"临时豁免"。真修路径:TCA `BindableAction` Reducer 改造 → View 改用 `$store.X` 直接绑定，再逐条删 noqa。**不要把 noqa sweep 当作"修完了"** — lint 归零 ≠ 底层 Perception 追踪问题解决。

> 同模式 3 次内复发 = 单纯人工 review 不可靠，必 lint + runtime 双层防护。

## 关联

- 配对原则（本条是五大触发点细则）
- 协调端凭印象（sweep 漏多次）
- handoff escalation 漏 sweep
