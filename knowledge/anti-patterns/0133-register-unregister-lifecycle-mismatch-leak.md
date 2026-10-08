---
doc_id: "ap-0133"
container: anti-patterns
platform: cross
summary: "0133 register/unregister 跨生命周期级别不对称 → 重复注册泄漏"
---

# 0133 register/unregister 跨生命周期级别不对称 → 重复注册泄漏

- **平台**:Android / iOS
- **复发次数**:0

## ❌ 错误

注册系统回调(`ComponentCallbacks` / `BroadcastReceiver` / `NotificationCenter observer` / KVO / lifecycle listener)时,**注册点的生命周期级别 ≠ 反注册点的生命周期级别**:

```kotlin
override fun onResume() {
    memoryCallback = ...
    requireContext().registerComponentCallbacks(memoryCallback)   // 注册在 onResume
}
override fun onDestroyView() {
    requireContext().unregisterComponentCallbacks(memoryCallback)  // 反注册在 onDestroyView
    // ⚠️ onResume 频率 > onDestroyView:onPause→onResume 不触发 onDestroyView
    //   → memoryCallback 被重新 assign + 重复 register,旧 register 未反注册 → 泄漏 + 重复回调
}
```

后果:每次 pause→resume 多注册一次 → N 次回调风暴 + 旧 callback 持 Context 引用泄漏。

## 为什么错

注册与反注册的生命周期级别不匹配,导致 View 重建 / pause-resume 时旧注册悬挂。

## ✅ 正确

```kotlin
override fun onResume() { ...; registerComponentCallbacks(memoryCallback) }
override fun onPause() { ...; unregisterComponentCallbacks(memoryCallback) }   // ← 同级别配对
```

**invariant:注册点的生命周期级别 = 反注册点的生命周期级别**。常见配对:

| 注册 | 反注册 |
|---|---|
| onCreate | onDestroy |
| onStart | onStop |
| onResume | onPause |
| onCreateView / onViewCreated | onDestroyView |
| SwiftUI `.onAppear` | `.onDisappear` |
| iOS `viewDidAppear` | `viewWillDisappear` |
| KVO addObserver(init) | removeObserver(deinit) |

铁律:
1. 任何 `register*` / `addObserver*` / `subscribe` 必有同生命周期级别的反注册。
2. Fragment 反注册必用 `viewLifecycleOwner` 而非 `requireActivity()`(View 复用场景)。
3. 跨 Feature audit:全工程 grep `registerComponentCallbacks` / `registerReceiver` / `addObserver` verify 配对。
4. 优先用自动管理 API(`viewLifecycleOwner.lifecycleScope` / Compose `DisposableEffect`)。

## lint 状态

❓ 中等(语法可 grep,语义配对需人工)— soft 警告:同文件内 register*/unregister* 出现在不同生命周期方法 → 提示人工 verify 配对。

## 关联

- SwiftUI 懒加载子 View(同源:生命周期事件配对失误 → 内存 / 行为异常)
