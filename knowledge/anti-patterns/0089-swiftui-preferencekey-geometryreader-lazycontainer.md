---
doc_id: "ap-0089"
container: anti-patterns
platform: ios
summary: "SwiftUI PreferenceKey + GeometryReader 在 LazyContainer Scro…"
---

# 0089 — SwiftUI PreferenceKey + GeometryReader 在 LazyContainer ScrollView 内不可靠

- **平台**:iOS
- **复发次数**:1
- **lint 状态**:❌ 无 lint（运行时才能发现，只能靠知识沉淀）

## 现象

在 `LazyVStack` / `LazyHStack` 外包的 `ScrollView` 里，用 `GeometryReader { geo in Color.clear.preference(key: SomeKey.self, value: geo.frame(in: .named("space")).minY) }` + `.onPreferenceChange(SomeKey.self)` 监听滚动偏移，实测在真机快速 fling 期间几乎不触发（49 秒仅 1 次，期望百次以上）。

## 根因

SwiftUI preference 系统对 PreferenceKey value 做**去重 + 内部节流**。LazyContainer 内的 view 被懒惰挂载卸载，content frame 在 ScrollView 坐标系里的 `minY` 并不连续变化——SwiftUI 内部优化使得大多数滚动帧不触发 preference 下传。此机制在真机快速滑动时表现最差（几乎无回调），模拟器可能表现略好（误导判断）。

## 修法

需要可靠滚动检测时，**不用 PreferenceKey + GeometryReader**，改用以下方案:

1. **UIScrollView delegate（UIKit interop）**:`UIViewRepresentable` 包住 ScrollView，在 `scrollViewDidScroll` delegate 直接回调（100% 可靠）
2. **`ScrollView` + `onScroll` modifier（iOS 17+）**:`.onScrollGeometryChange(for:)` 官方 API
3. **去掉滚动检测，改用 cancel 机制**:利用 `.task(id:)` cancel 本身（fast swipe → task cancel → 自然放弃），无需感知"是否正在滚动"

iOS 16 兼容且追求简单:**方案 3**。

## 反例

```swift
// ❌ 会漏掉大量滚动事件:
GeometryReader { geo in
    Color.clear.preference(key: ScrollOffsetKey.self,
        value: geo.frame(in: .named("scroll")).minY)
}
// + .onPreferenceChange(ScrollOffsetKey.self) { scrollState.notifyScrolled() }
```
