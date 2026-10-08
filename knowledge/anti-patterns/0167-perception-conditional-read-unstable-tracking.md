---
doc_id: "ap-0167"
container: anti-patterns
platform: ios
summary: "0167 Perception 条件读取导致依赖追踪集不稳定"
---

# 0167 Perception 条件读取导致依赖追踪集不稳定

- **平台**:iOS
- **复发次数**:1

## ❌ 错误

在 `withPerceptionTracking` 观察闭包调用的方法中使用 early return，而某些需要触发重跑的状态字段只在 return 之后读取。某播放开关首次变化可能不生效，直到另一个仍被追踪的字段变化后才恢复。

```swift
func applyState(_ state: State) {
    let items = Array(state.items)
    if shouldReset { return }
    if cachedPlayback != state.playbackEnabled { /* update */ }
}
```

## 为什么错

- Perception 的追踪集取决于最近一次闭包执行时实际读取的字段，而不是历次读取字段的并集。
- 一次走 early-return 路径，就会让 return 之后的字段退出当前追踪集。
- 该字段后续变化不会触发 `onChange`，症状因其他状态变化而暂时恢复，容易被误判为偶发或时序问题。

## ✅ 正确

- 在任何条件分支和 return 之前，无条件读取所有需要触发重跑的字段。
- 后续逻辑只消费这些提前读取的局部值，并在提前返回前同步必要的本地缓存。
- review 观察闭包时，逐个字段确认：该字段变化是否应触发重跑；若是，则所有执行路径都必须读取它。

## lint 状态

- ❌ 难以可靠静态检查：是否读全字段属于语义判断，简单 grep 误报较高。
- 人工 review：重点检查观察闭包调用链中的条件分支、early return 和间接字段读取。
- 关联：Perception 观察闭包需同时满足正确包裹与稳定依赖注册 — 同家族 [`0064`](./0064-tca-perception-bindable-withperceptiontracking.md)(漏包追踪容器)/ [`0087`](./0087-swiftui-tca-escaping-closure-withperceptiontracking.md)(逃逸闭包逃出作用域);本条是包裹存在但条件读取致依赖集不稳定,三者修复位置不同。
