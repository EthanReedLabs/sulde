---
doc_id: "ap-0016"
container: anti-patterns
platform: android
summary: "reduceResult 中产生 Command"
---

# 0016 — reduceResult 中产生 Command

- **平台**:Android(MVI)

## ❌ 错误

```kotlin
override fun reduceResult(state, intent: ResultIntent): ReduceResult {
    return when (intent) {
        is SubmitSucceeded -> ReduceResult(
            state = state.copy(...),
            command = LoadDetailCommand(...)  // ❌ ResultIntent 禁止产生 Command
        )
    }
}
```

## 为什么错

违反"两层终止"约束 → Command 链无限传递 → 回调栈爆炸 / 难调试 / 可能死循环。

## ✅ 正确

```kotlin
override fun reduceResult(state, intent: ResultIntent): ReduceResult {
    return when (intent) {
        is SubmitSucceeded -> ReduceResult(
            state = state.copy(...),
            sideEffects = listOf(NavigateToDetail(intent.id))  // ✅ 只允许 SideEffect
        )
    }
}
```

## lint 状态

- ⏳ 可静态扫:`reduceResult` 体内禁出现 `command =`(只允许 `sideEffects`)。

关联:0017(iOS TCA 同源 — Result Action 返回 `.run`)。
