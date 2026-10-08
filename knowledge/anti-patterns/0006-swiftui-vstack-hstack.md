---
doc_id: "ap-0006"
container: anti-patterns
platform: ios
summary: "SwiftUI 浮层用 VStack/HStack"
---

# 0006 — SwiftUI 浮层用 VStack/HStack

- **平台**:iOS

## ❌ 错误

```swift
VStack {
    overlayButton
    contentView
    actionRail
}
```

## ✅ 正确

```swift
ZStack(alignment: .topLeading) {
    contentView
    overlayButton.stagePosition(.topLeading, padding: 18)
    actionRail.stagePosition(.bottomTrailing, hPadding: 18, vPadding: 152)
}
```

**判断规则**:设计稿 layout=none(子项叠放/绝对定位)→ 用 ZStack + alignment + padding,不用 VStack/HStack 排开。

## lint 状态

- ❌ 难静态检查 → 人工 review。
- 关联:0002(Android 同源 — 浮层误用 LinearLayout)。
