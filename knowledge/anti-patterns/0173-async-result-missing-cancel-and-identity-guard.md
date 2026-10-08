---
doc_id: "ap-0173"
container: anti-patterns
platform: ios
summary: "0173 异步结果写回缺少取消与 identity 双保险"
---

# 0173 异步结果写回缺少取消与 identity 双保险

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

列表项选择或数据源切换后，只取消旧 effect，却在结果返回时不验证它是否仍属于当前状态：

```swift
return .run { send in
    let result = try await loader.load(requestIdentity)
    await send(.loaded(result))
}
.cancellable(id: CancelID.load, cancelInFlight: true)
```

反过来，只做 identity guard 而不取消旧任务也不完整。

## 为什么错

取消是协作式的，取消信号可能与完成回调竞速，依赖也可能未及时检查 cancellation，因此迟到结果仍可能抵达。identity guard 能保护结果所有权，却不能停止列表项选择或数据源切换后已经无用的工作。资源治理与状态正确性是两个独立目标。

## ✅ 正确

在 TCA 中同时使用两道闸：

1. 用 `.cancellable(id:cancelInFlight:)` 取消同类旧 effect，并在离开作用域时显式取消。
2. 让 action 携带发起时的列表项 identity 与数据源 identity；reducer 写回前与当前 state 比对，不一致则丢弃。

```swift
case let .loaded(requestIdentity, result):
    guard requestIdentity == state.currentIdentity else { return .none }
    state.result = result
    return .none
```

## lint 状态

- ❌ effect 与结果所有权的配对属于语义级检查。
- CI：覆盖取消信号与完成回调竞速，以及列表项选择、数据源切换后的迟到结果不修改 state。
- 关联：入口防双发解决触发次数，本条解决异步结果归属与资源回收。
