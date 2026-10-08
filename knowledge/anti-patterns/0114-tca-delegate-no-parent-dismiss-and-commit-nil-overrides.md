---
doc_id: "ap-0114"
container: anti-patterns
platform: ios
summary: "TCA picker delegate 不关父态 + commit(nil) 误擦互斥兄弟字段"
---

# 0114 — TCA picker delegate 不关父态 + commit(nil) 误擦互斥兄弟字段

- **平台**:iOS(TCA picker delegate + commit 模式)
- **复发次数**:0

## ❌ 错误

TCA 多层 picker(父容器 + 子 sheet)中,写入型 delegate(`appendXxx` / `applyXxx`)只关闭自己的子 sheet 而**不关闭父容器** → 用户被迫走父容器的"另一个出口"(Continue / commit)→ 父 reducer 在 `commit` case 无条件清互斥兄弟字段 → 用户刚写的兄弟字段被 commit(nil) 误擦。

```swift
// 子 Feature: addToPrompt 只关自己的子 sheet,不关父 picker
case .view(.addToPromptTapped):
    state.showCustomSheet = false   // 只关子层
    return .send(.delegate(.appendCustomToPrompt(text)))  // 父 picker 仍开着

// 父 Feature: committed 无条件清互斥兄弟字段
case .picker(.presented(.delegate(.committed(let preset)))):
    state.selectedPreset = preset
    state.customText = nil   // ← 用户点 Continue(无选)→ committed(nil) → 把刚写的 custom 擦了
    state.picker = nil
```

**现象**:用户加完自定义内容,prompt 有文字但行回占位 — custom 被 Continue 提交时擦除。

## 为什么错

- **写入型 delegate(`appendXxx`)只关子层不关父容器** → 用户写完没"完成"位,被迫走父容器的另一个出口(Continue / commit)。
- **互斥清字段写在 commit case 但没区分 `commit(有值)` vs `commit(nil)`** → 空提交误擦刚写的兄弟字段。

## ✅ 正确

```swift
// 写入即关父容器(回到宿主页看结果)
case .delegate(.appendCustomToPrompt(let text)):
    state.prompt += sep + text
    state.customText = text
    state.selectedPreset = nil
    state.picker = nil          // ← 加完即关 picker,用户不再走 Continue
    state.showCustomToast = true

// 互斥只在真选了 preset 才清
case .delegate(.committed(let preset)):
    state.selectedPreset = preset
    if preset != nil { state.customText = nil }  // commit(nil) 不擦
    state.picker = nil
```

## 判定线

- TCA picker delegate 写入型 case 漏 `state.<parentPicker> = nil` → ❌。
- `commit` case 无条件清互斥兄弟字段 → ❌(必区分 `commit(有值)` vs `commit(nil)`)。

## lint 状态

- ❌ iOS 无法静态扫(运行时 state 流);仅人工 review。`/code-review` checklist 加「写入型 delegate 是否关闭父容器 + 互斥清字段是否区分 nil 提交」。

## How to apply

- 协调端 task md 涉及 TCA picker 写入型 delegate(`appendXxx` / `applyXxx`)时,代码示例必含 `state.<parentPicker> = nil`。
- 涉及 picker `committed` reducer case 时,**必区分 `commit(有值)` vs `commit(nil)`**(用 `if preset != nil { ... }` 守卫)。
- `/code-review` checklist 加 2 条:写入型 delegate 是否关闭父容器?`commit` 互斥清字段是否区分 nil 提交?

## 端属性

- iOS 首次踩,实证修复。
- Android(MVI / Compose 同源)→ ⏳ 待 audit(双端 idiom 不同源,Android 可能不存在;待真机回归暴露后再派,防凭印象推 Android 有同款 bug)。

## 关联

- 登录拦截 delegate 设计了但父 reducer 没接住(同家族 delegate flow 设计缺陷)。
- TCA `@Perception.Bindable` + `WithPerceptionTracking` 必配对(同 TCA flow 类)。
