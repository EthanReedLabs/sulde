---
doc_id: "ap-0111"
container: anti-patterns
platform: ios
summary: "SwiftUI 嵌套空 Button + 自定义 tap modifier 手势冲突"
---

# 0111 — SwiftUI 嵌套空 Button + 自定义 tap modifier 手势冲突

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

SwiftUI 视图嵌套 `Button {} label:` 空 action + 自定义 tap modifier(`.debouncedTap` / `.onTapGesture` 等)挂真 action,尤在 `ScrollView(.horizontal)` / `List` 容器内。

```swift
Button {} label: {          // 外层空 action — 在 ScrollView 内吞 tap
    Text(tag)
        .padding(...)
        .background(...)
}
.debouncedTap(delay: 0.3) { tagSelected(tag) }  // 内层真 action 拿不到手势
```

## 为什么错

外层空 action `Button` 在 ScrollView 内会吞 tap 事件 → 内层自定义 tap modifier 拿不到手势 → 点击无响应。reducer wire 可以完整正确,但 UI 层手势链断裂后 action 永不触发。

## ✅ 正确

```swift
Button(action: { tagSelected(tag) }) {   // 单层,action 直接挂 Button
    Text(tag)
        .padding(...)
        .background(...)
}
```

## 判定线

- SwiftUI 视图 grep `Button \{\}` 命中 ≥1 + 同层 `.tap` modifier → 反模式。
- `ScrollView(.horizontal)` / `List` 内嵌 Button 尤需注意。

## How to apply

- 单 chip / tag / cell pattern → 单层 `Button(action:) { ... }`,**不嵌套空 Button**。
- 自定义 tap modifier 仅用于 non-Button container(如 `Text` / `HStack` 无 Button 包裹时)。
- modifier 定义本身可保留,但 Button 容器场景直接用 `Button(action:)` 替代。

## lint 状态

- grep `Button \{\}` + 同层 `.tap` modifier 可自动化软警告。

## 关联

- SwiftUI 高频手势组件性能与正确性陷阱(同类手势领域,不同维度)。
- SwiftUI Button `.frame()` 无 `.contentShape()` — hit-testing 命中区偏小(同为 Button 交互问题)。
