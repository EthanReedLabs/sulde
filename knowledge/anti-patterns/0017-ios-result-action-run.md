---
doc_id: "ap-0017"
container: anti-patterns
platform: ios
summary: "iOS Result Action 返回 `.run`"
---

# 0017 — iOS Result Action 返回 `.run`

- **平台**:iOS(TCA)

## ❌ 错误

```swift
case .submitSucceeded(let id):
    state.taskId = id
    return .run { send in           // ❌ Result Action 禁止返回 .run
        let detail = try await client.fetch(id)
        await send(.detailLoaded(detail))
    }
```

## 为什么错

违反 TCA 两层终止约束 → Effect 链无限传递,难调试 / 可能死循环。

## ✅ 正确

```swift
case .submitSucceeded(let id):
    state.taskId = id
    return .send(.delegate(.navigateToDetail(id)))  // ✅ 只能 .none 或 .send(.delegate)
```

## lint 状态

- ⏳ 可静态扫:Result/Delegate action 分支体内禁出现 `.run {`。

关联:0016(Android MVI 同源 — reduceResult 产生 Command)。
